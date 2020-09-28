import boto3
import json
import uuid
import datetime

dynamodb = boto3.resource('dynamodb', region_name='<AWS_REGION>') # TODO:: Update with aws-region where thes stack is deployed
table = dynamodb.Table('aws-samples-budgets') # TODO:: Once stack is deployed, update the DynamoDB Table Name

def insert_data(db_item):
    table.put_item(Item=db_item)

budgets = [
    {
        "partitionKey": "BUDGET",
        "rangeKey": str(uuid.uuid4()),
        "budgetName": "bu1-monthly-budget",
        "budgetLimit": 0,
        "actualSpend": 0,
        "forecastedSpend": 0,
        "approverEmail": "admin1@email.com", # Email address of the admin for the business unit
        "notifySNSTopic": "arn:aws:sns:ap-south-1:1234567891235:approval-notification", # Update the SNS notification for the business unit
        "accruedForecastedSpend": 0,
        "accruedBlockedSpend": 0,
        "accruedApprovedSpend": 0,
        "businessEntity": "business_entity_1",
        "budgetForecastProcessed": False,
        "budgetUpdatedAt": str(datetime.datetime.utcnow())
    },
    {
        "partitionKey": "BUDGET",
        "rangeKey": str(uuid.uuid4()),
        "budgetName": "bu2-monthly-budget",
        "budgetLimit": 0,
        "actualSpend": 0,
        "forecastedSpend": 0,
        "approverEmail": "admin2@email.com", # Email address of the admin for the business unit
        "notifySNSTopic": "arn:aws:sns:ap-south-1:1234567891235:approval-notification", # Update the SNS notification for the business unit
        "accruedForecastedSpend": 0,
        "accruedBlockedSpend": 0,
        "accruedApprovedSpend": 0,
        "businessEntity": "business_entity_2",
        "budgetForecastProcessed": False,
        "budgetUpdatedAt": str(datetime.datetime.utcnow())
    },
    {
        "partitionKey": "BUDGET",
        "rangeKey": str(uuid.uuid4()),
        "budgetName": "bu3-monthly-budget",
        "budgetLimit": 0,
        "actualSpend": 0,
        "forecastedSpend": 0,
        "approverEmail": "admin3@email.com", # Email address of the admin for the business unit
        "notifySNSTopic": "arn:aws:sns:ap-south-1:1234567891235:approval-notification", # Update the SNS notification for the business unit
        "accruedForecastedSpend": 0,
        "accruedBlockedSpend": 0,
        "accruedApprovedSpend": 0,
        "businessEntity": "business_entity_3",
        "budgetForecastProcessed": False,
        "budgetUpdatedAt": str(datetime.datetime.utcnow())
    },
    {
        "partitionKey": "BUDGET",
        "rangeKey": str(uuid.uuid4()),
        "budgetName": "bu4-monthly-budget",
        "budgetLimit": 0,
        "actualSpend": 0,
        "forecastedSpend": 0,
        "approverEmail": "admin4@email.com", # Email address of the admin for the business unit
        "notifySNSTopic": "arn:aws:sns:ap-south-1:1234567891235:approval-notification", # Update the SNS notification for the business unit
        "accruedForecastedSpend": 0,
        "accruedBlockedSpend": 0,
        "accruedApprovedSpend": 0,
        "businessEntity": "business_entity_4",
        "budgetForecastProcessed": False,
        "budgetUpdatedAt": str(datetime.datetime.utcnow())
    }
]

for item in budgets:
    insert_data(item)
