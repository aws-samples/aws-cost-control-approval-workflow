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
import requests
import json
import logging
import boto3
import os
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)
region = os.environ['AWS_REGION']
budgets_table_name = os.environ['BudgetsTable']
dynamodb = boto3.resource('dynamodb', region_name=region)
budgets_table = dynamodb.Table(budgets_table_name)
request_partition = 'REQUEST'
budget_partition = 'BUDGET'

def lambda_handler(event, context):
    logger.info(json.dumps(event))
    success_responseData = {
        "Status": "SUCCESS",
        "Reason": "Approved",
        "UniqueId": 'None',
        "Data": "Owner approved the stack creation"
    }
    if event['queryStringParameters'] and 'requestId' in event['queryStringParameters'] and 'requestStatus' in event['queryStringParameters']:
        
        request_id = event['queryStringParameters']['requestId']
        request_status = event['queryStringParameters']['requestStatus']
        success_responseData['UniqueId'] = request_id
        request = get_request_item(request_id)
        requested_amt = request['pricingInfoAtRequest']['EstCurrMonthPrice']
        business_entity_id = request['businessEntityId']
        budget = get_budgets_for_request(business_entity_id)
        accrued_blocked = budget['accruedBlockedSpend']
        accrued_forecast = budget['accruedForecastedSpend']
        accrued_approved = budget['accruedApprovedSpend']
        requested_amt_monthly = request['pricingInfoAtRequest']['31DayPrice']
        wait_url = request['stackWaitUrl']        
        try:
            logger.info("Accruals before processing the request Blocked: {}, Forcasted: {}, Approved: {}".format(accrued_blocked, accrued_forecast, accrued_approved))
            if request['requestStatus'] == 'PENDING' or request['requestStatus'] == 'BLOCKED':
                if  request_status == "Approve":
                    success_responseData['Status'] = "SUCCESS"
                    update_approval_request_status(request_id)
                    # Recalcuate the accruals and move the requested amt to forecasted from blocked
                    accrued_blocked = accrued_blocked - requested_amt_monthly
                    accrued_forecast = accrued_forecast + requested_amt
                    accrued_approved = accrued_approved + (requested_amt_monthly - requested_amt)
                    update_accrued_amt(business_entity_id, accrued_forecast, accrued_blocked, accrued_approved)
                elif request_status == "Reject":
                    success_responseData['Status'] = "FAILURE"
                    success_responseData['Reason'] = "Rejected"
                    success_responseData['Data'] = "Admin rejected the stack"
                    update_rejection_request_status(request_id)
                    # Remove the blocked amount since request is rejected
                    accrued_blocked = accrued_blocked - requested_amt_monthly
                    update_accrued_amt(business_entity_id, accrued_forecast, accrued_blocked, accrued_approved)

                response = requests.put(wait_url, data=json.dumps(success_responseData))
                logger.info("Successfully responded for waithandle with response: {}".format(response))
            else:
                logger.info('Request can abe approved/rejected only when it is in blocked or pending state')
        except Exception as e:
            logger.error("Failed approving the request: {}".format(e))
        response = {"data":'Successfully Processed the request'}
        return {'statusCode':'200','body':json.dumps(response)}
    else:
        response = {"error":'Mandatory request paramters not found' }
        return {'statusCode':'200','body':json.dumps(response)}

# updates the rejection status in database
def update_rejection_request_status(request_id):
    logger.info('Received request to terminate a stack with request id: {}'.format(request_id))
    response = budgets_table.update_item(
        Key={'partitionKey': request_partition, 'rangeKey': request_id},
        UpdateExpression="set requestStatus = :s, requestRejectionTime=:a, resourceStatus=:r",
        ExpressionAttributeValues={
            ':s': 'REJECTED_ADMIN',
            ':a': str(datetime.utcnow()),
            ':r': 'REJECTED'
        },
        ReturnValues="UPDATED_NEW"
    )
    logger.debug("UpdateItem succeeded:")
    logger.debug(json.dumps(response))  
    
# Update the status of the request in dynamo-db
def update_approval_request_status(request_id):
    response = budgets_table.update_item(
        Key={'partitionKey': request_partition, 'rangeKey': request_id},
        UpdateExpression="set requestStatus = :s, requestApprovalTime=:a, resourceStatus=:r",
        ExpressionAttributeValues={
            ':s': 'APPROVED_ADMIN',
            ':a': str(datetime.utcnow()),
            ':r': 'ACTIVE'
        },
        ReturnValues="UPDATED_NEW"
    )
    logger.debug("UpdateItem succeeded:")
    logger.debug(json.dumps(response))      

# Get the request item for a given request id
def get_request_item(request_id):
    response = budgets_table.get_item(
        Key={'partitionKey': request_partition, 'rangeKey': request_id},
        ProjectionExpression='stackWaitUrl, requestStatus, businessEntityId, pricingInfoAtRequest'
    )
    return response['Item']

# Update the Accruals in database
def update_accrued_amt(business_entity_id, accruedForecastedSpend, accruedBlockedSpend, accruedApprovedSpend):
    logger.info("Update the Budget with new accrued amounts Blocked: {}, Forcasted: {}, Approved: {}".format(accruedBlockedSpend, accruedForecastedSpend, accruedApprovedSpend))
    update_expression = "set accruedForecastedSpend=:a, accruedBlockedSpend=:b, accruedApprovedSpend=:c"
    expression_attributes = {
        ':a': accruedForecastedSpend,
        ':b': accruedBlockedSpend,
        ':c': accruedApprovedSpend
    }
    response = budgets_table.update_item(
        Key={'partitionKey': budget_partition, 'rangeKey': business_entity_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attributes,
        ReturnValues="UPDATED_NEW"
    )
    logger.info('Successfully Updated accrued Amt for Key: {} with response {}'.format(business_entity_id, response))
    return True

# Gets the Budget information for a given business entity Id
def get_budgets_for_request(business_entity_id):
    response = budgets_table.get_item(
        Key={'partitionKey': budget_partition, 'rangeKey': business_entity_id},
        ProjectionExpression='accruedForecastedSpend, accruedBlockedSpend, accruedApprovedSpend'
    )
    return response['Item']