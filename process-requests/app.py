################################################################################
#
# MIT No Attribution
#
# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
################################################################################
import calendar
import json
import logging
import os
from datetime import datetime

import boto3
import requests
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)
region = os.environ['AWS_REGION']
budgets_table_name = os.environ['BudgetsTable']
dynamodb = boto3.resource('dynamodb', region_name=region)
budgets_table = dynamodb.Table(budgets_table_name)
sns = boto3.resource('sns')
budgets_partition_key = 'BUDGET'
requests_partition_key = 'REQUEST'
saved_req_status = 'SAVED'
pending_req_status = 'PENDING'
blocked_req_status = 'BLOCKED'


def lambda_handler(event, context):
    logger.info(json.dumps(event))
    # Get Budget Info
    budget_info = get_budget_info()
    # convert List to Dict for easier lookup
    budget_dict = {}
    update_budget_accruals = False
    for budget in budget_info:
        business_entity = budget['businessEntity']
        if not budget['budgetForecastProcessed']:
            logger.info("New Forecast Available for {}, replacing the accruedForecast with forecast from AWS budgets".format(business_entity))
            budget['accruedForecastedSpend'] = budget['forecastedSpend']
            update_budget_accruals = True
        else:
            logger.info("No Budget updated available for {} ".format(business_entity))
        budget_dict[business_entity] = budget
    logger.info("Local Dictionary for Budgets: {}".format(budget_dict))
    # Get Request that are in pending state
    pending_requests = get_requests(pending_req_status)

    for pending_request in pending_requests:
        business_entity = pending_request['businessEntity']
        if 'pendingRequestExists' in budget_dict[business_entity]:
            # there could be multiple requests for same business Entity, just skips those
            continue
        else:
            budget_dict[business_entity]['pendingRequestExists'] = True

    pending_request_count = len(pending_requests)
    if pending_request_count > 0:
        # recompute blocked requests to see if there is a change in forecast
        process_requests(pending_requests, budget_dict)
        update_budget_accruals = True

    # Get if there are any blocked requests
    blocked_requests = get_requests(blocked_req_status)

    blocked_request_count = len(blocked_requests)
    if blocked_request_count > 0:
        # Process blocked requests for each Business Entity
        process_requests(blocked_requests, budget_dict)
        update_budget_accruals = True

    # Get requests in SAVED state
    saved_requests = get_requests(saved_req_status)

    saved_request_count = len(saved_requests)
    if saved_request_count > 0:
        # process requests that are in saved state
        process_requests(saved_requests, budget_dict)
        update_budget_accruals = True

    if update_budget_accruals:
        logger.info("Updating Budgets Accruals")
        # update the budgets with newly calculated accrued amts
        update_accrued_amt(budget_dict)


def process_requests(requests, budget_dict):
    for request in requests:
        request_id = request['rangeKey']
        budget = budget_dict[request['businessEntity']]
        logger.info("Available Budget while processing request {} is {}".format(request_id, budget))
        budget_amt = budget['budgetLimit']
        curr_req_status = request['requestStatus']
        requested_amt = request['pricingInfoAtRequest']['EstCurrMonthPrice']  # EstCurrMonthPrice
        requested_amt_monthly = request['pricingInfoAtRequest']['31DayPrice']  # EstCurrMonthPrice
        logger.info("Pricing info for request {} is {}".format(request_id, request['pricingInfoAtRequest']))
        blocked_amt = budget['accruedBlockedSpend']
        approved_amt = budget['accruedApprovedSpend']
        forecast_spend = budget['accruedForecastedSpend'] if budget['accruedForecastedSpend'] > 0 else budget['forecastedSpend']
        remaining_amt = budget_amt - forecast_spend - requested_amt_monthly - blocked_amt - approved_amt
        logger.info("Remaining Amount for request {} after calculation is {}".format(request_id, remaining_amt))
        if remaining_amt < 0:
            logger.info("No Enough budget left for request {}".format(request_id))
            if curr_req_status == saved_req_status:
                logger.info("Request is in SAVED state, adjusting the local accruals before further processing... Request Id : {}".format(request_id))
                budget['accruedBlockedSpend'] = blocked_amt + requested_amt_monthly
            if not 'pendingRequestExists' in budget or not budget['pendingRequestExists'] or (
                    not budget['budgetForecastProcessed'] and curr_req_status == pending_req_status):
                logger.info("There is no pending request exist for business entity or there is a pricing rebase.. update the status and notify admin. Request Id: {}".format(request_id))
                # mark the status of the request denoting waiting for approval
                update_request_status(request_id, pending_req_status, budget['rangeKey'])
                # send approval to admin
                notify_admin(request, budget)
                budget['pendingRequestExists'] = True
            elif curr_req_status == saved_req_status:
                logger.info('Pending request exists for business entity, keeping the request in blocked state {}'.format(request_id))
                # mark rest of the requests denoting blocked by a existing request
                update_request_status(request_id, blocked_req_status, budget['rangeKey'])
        else:
            logger.info('Request is within the budget, prepping to auto approve the request {}'.format(request_id))
            budget['accruedForecastedSpend'] = forecast_spend + requested_amt
            budget['accruedApprovedSpend'] = approved_amt + (requested_amt_monthly - requested_amt)
            # if request is in blocked state, it means that a blocked request is rejected, we must
            # deduct the blocked amount and add it forecast amount since we would added to blocked amt
            # when we marked this request as blocked
            if curr_req_status in (pending_req_status, blocked_req_status):
                budget['accruedBlockedSpend'] = blocked_amt - requested_amt_monthly
                budget['pendingRequestExists'] = False

            # approve the request
            approve_request(request_id, request['stackWaitUrl'])
            # mark the request status as auto approved by the system
            update_request_status(request_id, 'APPROVED_SYSTEM', budget['rangeKey'])
            # logger.info("Auto approve requests if there is any't blocked amt") 


# Approve a request id since it falls within budget
def approve_request(request_id, approval_url):
    logger.info("Request received to auto approval a product with request Id: {}".format(request_id))
    success_response_data = {
        "Status": "SUCCESS",
        "Reason": "APPROVED",
        "UniqueId": request_id,
        "Data": "System approved the stack creation"
    }
    response = requests.put(approval_url, data=json.dumps(success_response_data))
    logger.info("Successfully auto approved a request with request id: {} with response {}".format(request_id, response))


# Notify an admin over a SNS topic
def notify_admin(request, budget):
    logger.info("Request received to notify admin for requestid : {}".format(request['rangeKey']))
    now = datetime.now()
    month = now.month
    year = now.year
    curr_month_name = calendar.month_name[month] + ', ' + str(year)

    topic_arn = budget['notifySNSTopic']
    topic = sns.Topic(topic_arn)
    email_id = request['requestorEmail']
    instance_type = request['requestPayload']['InstanceType']
    approval_url = request['requestApprovalUrl']
    rejection_url = request['requestRejectionUrl']
    budget_limit = budget['budgetLimit']
    accrued_blocked = budget['accruedBlockedSpend']
    requested_amt_31days = request['pricingInfoAtRequest']['31DayPrice']
    forecasted_spend = budget['accruedForecastedSpend'] + budget['accruedApprovedSpend']
    actual_spend = budget['actualSpend']
    response = topic.publish(
        Subject='Request for approval to launch a Linux EC2 Instance',
        Message='\
        Dear Admin,\n\
        An user (' + email_id + ') has requested to launch a Linux EC2 instance (' + instance_type + ').\n\n\
        Monthly Budget Limit : ' + str(budget_limit) + '\n\
        Forecasted spend for month of ' + curr_month_name + ': ' + str(forecasted_spend)+'\n\
        Actual spend for month of ' + curr_month_name + ' (MTD): ' + str(actual_spend)+'\n\
        Total spend of pending requests in pipeline (exclusive of current request): ' + str(accrued_blocked - requested_amt_31days) + '\n\
        Exception requested amount (Monthly Recurring): ' + str(requested_amt_31days) + '\n\
        \n\nKindly act by clicking the below URLs.\n\n' +
        'Approval Url (click to approve) ' + approval_url +
        '\n\nRejection Url (click to reject) ' + rejection_url +
        '\n\nPlease note that request will be auto rejected in 12 hrs if no action is taken\n\n\
        Thanks,\n\
        Product Approval Team\n')
    logger.info("Status of email notification: {}".format(response))
    return True


# update accruals in the database
def update_accrued_amt(budget_dict):
    logger.info("Updated Dict Object before updating the accrued spends: {}".format(budget_dict))
    for key, value in budget_dict.items():
        logger.info("Updating accrued Amt for key {}".format(key))
        update_expression = "set accruedForecastedSpend=:a, accruedBlockedSpend=:b, accruedApprovedSpend=:c"
        expression_attributes = {
            ':b': value['accruedBlockedSpend'],
            ':a': value['accruedForecastedSpend'],
            ':c': value['accruedApprovedSpend']
        }
        if not value['budgetForecastProcessed']:
            logger.info("Set budgetForcast Processed to True for business entity {}".format(key))
            update_expression = update_expression + ', budgetForecastProcessed=:e, budgetForecastProcessedAt=:d'
            expression_attributes[':e'] = True
            expression_attributes[':d'] = str(datetime.utcnow())

        response = budgets_table.update_item(
            Key={'partitionKey': budgets_partition_key, 'rangeKey': value['rangeKey']},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_attributes,
            ReturnValues="UPDATED_NEW"
        )
        logger.info('Successfully Updated accrued Amt for Key: {} with response {}'.format(key, response))
    return True


# get budgets for all business entities
def get_budget_info():
    response = budgets_table.query(
        KeyConditionExpression=Key('partitionKey').eq(budgets_partition_key),
        ProjectionExpression='notifySNSTopic,accruedApprovedSpend,businessEntity,rangeKey,accruedBlockedSpend,actualSpend,approverEmail,budgetLimit,forecastedSpend,accruedForecastedSpend,budgetForecastProcessed'
    )
    logger.info("Budget Info fetched from database")
    return response['Items']


# Get requests by state
def get_requests(request_state):
    response = budgets_table.query(
        IndexName='query-by-request-status',
        KeyConditionExpression=Key('requestStatus').eq(request_state),
        ScanIndexForward=True,
        ProjectionExpression='stackWaitUrl,rangeKey,requestorEmail,requestApprovalUrl,pricingInfoAtRequest,requestPayload,businessEntity,requestStatus,requestRejectionUrl'
    )
    logger.info("Requests fetched from DB for state: {}, request count {}".format(request_state, len(response['Items'])))
    return response['Items']


# Update the status of the request in dynamo-db
def update_request_status(request_id, request_status, busines_entity_id):
    update_expression = "set requestStatus = :s, businessEntityId=:b"
    expression_attributes = {
        ':s': request_status,
        ':b': busines_entity_id,
        # ':r': 'Active'
    }
    if request_status == "APPROVED_SYSTEM":
        update_expression = update_expression + ", requestApprovalTime=:c, resourceStatus=:d"
        expression_attributes[':c'] = str(datetime.utcnow())
        expression_attributes[':d'] = 'ACTIVE'

    response = budgets_table.update_item(
        Key={'partitionKey': requests_partition_key, 'rangeKey': request_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attributes,
        ReturnValues="UPDATED_NEW")
    logger.debug("UpdateItem succeeded:")
    logger.debug(json.dumps(response))
