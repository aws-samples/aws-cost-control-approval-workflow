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
import json
import logging
import boto3
import os
from datetime import datetime
from boto3.dynamodb.conditions import Key
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)
region = os.environ['AWS_REGION']
budgets_table_name = os.environ['BudgetsTable']
dynamodb = boto3.resource('dynamodb', region_name=region)
budgets_table = dynamodb.Table(budgets_table_name)
partition_key = 'BUDGET'
req_partition_key = 'REQUEST'
client = boto3.client('budgets')

def lambda_handler(event, context):
    logger.info(json.dumps(event))
    account_id = os.environ['AccountId']
    try:
        # Fetch available business units from database
        business_entities = get_business_entities()
        # Check for request from S3
        if 'Records' in event: 
            for record in event['Records']:
                key = record['s3']['object']['key']
                # Look for manifest file only, it may be the case that there are multiple files uploaded by CUR
                # we do not want to rebase multiple times
                if key.split(".")[-1] == "json":
                    # fetch pricing and save the data to ddb
                    logger.info("Pricing Manifest file found at {}".format(key))
                    for entity in business_entities:
                        logger.info("Processing Budget for Entity {}".format(entity))
                        budget_name = entity['budgetName']
                        range_key = entity['rangeKey']
                        budget_info = get_budget_details(account_id, budget_name)
                        budget_amt = Decimal(budget_info['Budget']['BudgetLimit']['Amount'])
                        actual_spend = Decimal(budget_info['Budget']['CalculatedSpend']['ActualSpend']['Amount'])
                        forecast_spend = Decimal(budget_info['Budget']['CalculatedSpend']['ForecastedSpend']['Amount'])
                        # Reset accruedForcastedSpend whenever there is a budget update from AWS
                        update_pricing_info(range_key, budget_name, budget_amt, actual_spend, forecast_spend)
            return {'statusCode':'200', 'body':'Successfully rebased accruedForecastSpend'}
        # Monthly rebase of accruedApprovalSpend
        elif 'source' in event and event['source'] == 'aws.events': 
            logger.info("Event received from CloudWatchRule")
            for entity in business_entities:
                logger.info("Reset accruedApprovedSpend for business entity {}".format(entity))
                budget_name = entity['budgetName']
                range_key = entity['rangeKey']
                reset_accrued_approved_amt(range_key,budget_name)
            return {'statusCode':'200', 'body':'Successfully rebased AccruedApproval Amount'}
    except Exception as e:
        logger.error(e)
        return {'statusCode': '500', 'body':e}

# Reset Accruals in database
def reset_accrued_approved_amt(range_key, budget_name):
    logger.info("Resetting the accruedApprovedSpent at begining of the month for business entity id {}".format(range_key))
    response = budgets_table.update_item(
        Key={'partitionKey': partition_key, 'rangeKey': range_key},
        UpdateExpression="set accruedApprovedSpend=:a",
        ExpressionAttributeValues={':a': Decimal(0.0)},
        ReturnValues="UPDATED_NEW"
    )
    logger.info('Updated Pricing Info for Budget: {} with response {}'.format(budget_name, response))
    return True

# Update pricing information for given business entity
def update_pricing_info(range_key, budget_name, budget_limit, actual_spend, forcasted_spend):
    response = budgets_table.update_item(
        Key={'partitionKey': partition_key, 'rangeKey': range_key},
        UpdateExpression="set budgetLimit=:a, actualSpend=:b, forecastedSpend=:c, budgetUpdatedAt=:d, budgetForecastProcessed=:e",
        ExpressionAttributeValues={
            ':a': budget_limit,
            ':b': actual_spend,
            ':c': forcasted_spend,
            ':d': str(datetime.utcnow()),
            ':e': False,
        },
        ReturnValues="UPDATED_NEW"
    )
    logger.info('Updated Pricinig Info for Budget: {} with response {}'.format(budget_name, response))
    return True

# Get all budget information for all business entities
def get_business_entities():
    response = budgets_table.query(
        KeyConditionExpression=Key('partitionKey').eq(partition_key),
        ProjectionExpression='rangeKey,budgetName'
    )
    logger.info("Business Entities fetched from DB")
    return response['Items']
    
# Get budget details for a given account and budget name
def get_budget_details(account_id, budget_name):
    response = client.describe_budget(AccountId=account_id, BudgetName=budget_name)
    return response

# Get requests by state
def get_requests(request_state):
    response = budgets_table.query(
        IndexName='query-by-request-status',
        KeyConditionExpression=Key('requestStatus').eq(request_state),
        ScanIndexForward=True,
        ProjectionExpression='rangeKey,requestorEmail,requestApprovalUrl,pricingInfoAtRequest,accuredForcastedSpend, businessEntity'
    )
    logger.info("Business Entities fetched from DB")
    return response['Items']