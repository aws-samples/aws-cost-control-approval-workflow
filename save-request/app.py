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
import boto3
import requests
import json
import logging
from datetime import datetime
import os
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)
partition_key = 'REQUEST'
budget_parititon_key = 'BUDGET'
api_gw_url = os.environ['ApprovalUrl']
region = os.environ['AWS_REGION']
budgets_table_name = os.environ['BudgetsTable']
dynamodb = boto3.resource('dynamodb', region_name=region)
budgets_table = dynamodb.Table(budgets_table_name)

def lambda_handler(event, context):
    responseData = {'Status':'Request successfully saved to Dynamo DB'}
    logger.info(json.dumps(event))
    try:
        if event['RequestType'] == 'Delete':
            update_termination_request_status(event['StackId'].split("/")[-1])
            responseData = {'Status':'Request successfully updated as Terminated in Dynamo DB'}
            sendResponse(event, context,'SUCCESS',responseData)
            return True
        elif event['RequestType'] != 'Create':
            responseData = {'Staus':'No Special handling for Updated Stack, skip the event'}
            sendResponse(event, context,'SUCCESS',responseData)
            return True
        wait_url = event['ResourceProperties']['WaitUrl']
        email_id = event['ResourceProperties']['EmailID']
        approval_url = "{}?requestStatus={}&requestId={}".format(api_gw_url, 'Approve', event['StackId'].split("/")[-1])
        rejection_url = "{}?requestStatus={}&requestId={}".format(api_gw_url, 'Reject', event['StackId'].split("/")[-1])
        event['ResourceProperties']['StackId'] = event['StackId']
        pricing_info = json.dumps(event['ResourceProperties']['EC2Pricing'])
        logger.info(type(pricing_info))
        logger.info("Pricing Info: {}".format(pricing_info))
        business_entity = event['ResourceProperties']['BusinessEntity']
        event['ResourceProperties'].pop('EC2Pricing')
        event['ResourceProperties'].pop('BusinessEntity')
        db_item = {
                'partitionKey': partition_key,
                'rangeKey': event['StackId'].split("/")[-1],
                'requestApprovalUrl': approval_url,
                'requestRejectionUrl': rejection_url,
                'stackWaitUrl':wait_url,
                'requestTime': str(datetime.utcnow()),
                'requestorEmail': email_id,
                'requestStatus': 'SAVED',
                'resourceStatus': 'PENDING',
                'businessEntity': business_entity,
                'businessEntityId': '',
                'pricingInfoAtRequest': json.loads(pricing_info, parse_float=Decimal),
                'productName': event['ResourceProperties']['ProductName'],
                'requestPayload': event['ResourceProperties']
            }
        create_approval_req_item(db_item)
        sendResponse(event, context,'SUCCESS',responseData)
        return True
    except Exception as e:
         logger.info("Error while saving the request in datatbase, termiante the stack: {}".format(e))
         sendResponse(event, context, 'FAILED', {})
         return False

# Update the status of the request in dynamo-db
def update_termination_request_status(request_id):
    logger.info('Received termination request for stack id: {}'.format(request_id))
    existing_req = budgets_table.get_item(
        Key={'partitionKey':partition_key, 'rangeKey':request_id},
        ProjectionExpression='requestStatus, businessEntity, businessEntityId, pricingInfoAtRequest'
    )
    if 'Item' not in existing_req:
        return False
    logger.info('Fetched Request Item from Database: {}'.format(existing_req['Item']))
    requested_amt = existing_req['Item']['pricingInfoAtRequest']['EstCurrMonthPrice']
    requested_amt_monthly = existing_req['Item']['pricingInfoAtRequest']['31DayPrice']
    business_entity_id = existing_req['Item']['businessEntityId']
    request_status = existing_req['Item']['requestStatus']
    
    # if status is pending/rejected/blocked, then deduct from accrued blocked amt
    if len(business_entity_id) > 0 and (request_status == 'PENDING' or request_status == 'BLOCKED'):
        logger.info('Adjusting Accruals since request is in {} state'.format(request_status))
        budget_info = budgets_table.get_item(
            Key={'partitionKey':budget_parititon_key, 'rangeKey':business_entity_id},
            ProjectionExpression='accruedBlockedSpend'
        )
        accrued_blocked_spend = budget_info['Item']['accruedBlockedSpend']
        accrued_blocked_spend = accrued_blocked_spend - requested_amt_monthly
        logger.info("Clear the blocked amt if exists")
        response = budgets_table.update_item(
            Key={'partitionKey': budget_parititon_key, 'rangeKey': business_entity_id},
            UpdateExpression = "set accruedBlockedSpend=:b",
            ExpressionAttributeValues={
                ':b': accrued_blocked_spend
            },  
        ReturnValues="UPDATED_NEW")
        logger.info("Blocked amount cleared successfully: {}".format(response))
    update_expression =  "set resourceTerminationTime=:a, resourceStatus=:r"
    expression_attributes = {
        ':a': str(datetime.utcnow()),
        ':r': 'TERMINATED'
    }
    if request_status == 'PENDING' or request_status == 'BLOCKED' or request_status == 'SAVED':
        update_expression =  update_expression+", requestStatus=:c"
        expression_attributes[':c'] = 'REJECTED_SYSTEM'
    elif request_status != 'REJECTED_ADMIN':
        update_expression =  update_expression+", requestStatus=:c"
        expression_attributes[':c'] = request_status+'_TERMINATED'
    response = budgets_table.update_item(
        Key={'partitionKey': partition_key, 'rangeKey':request_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attributes,
        ReturnValues="UPDATED_NEW")
    logger.debug("UpdateItem succeeded:")
    logger.debug(json.dumps(response)) 
    return True
# Create an request in database
def create_approval_req_item(db_item):
    response = budgets_table.put_item(
        Item = db_item)
    logger.debug("CreateItem succeeded:")
    logger.debug(json.dumps(response))
# Send response to CFN
def sendResponse(event, context, responseStatus, responseData):
    response_body={'Status': responseStatus,
            'Reason': 'See the details in CloudWatch Log Stream ' + context.log_stream_name,
            'PhysicalResourceId': context.log_stream_name ,
            'StackId': event['StackId'],
            'RequestId': event['RequestId'],
            'LogicalResourceId': event['LogicalResourceId'],
            'Data': responseData}
    try:
        response = requests.put(event['ResponseURL'],
                        data=json.dumps(response_body))
        return True
    except Exception as e:
        logger.info("Failed executing HTTP request: {}".format(e))
    return False