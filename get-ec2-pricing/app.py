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
# Reference - https://s3.amazonaws.com/cloudformation-examples/lambda/amilookup.zip
import boto3
import simplejson as json
import logging
import os
import requests
import datetime, time
import calendar
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)
region = os.environ['AWS_REGION']

def lambda_handler(event,context):
    # Do not do anything for CFN Update and Delete
    if 'RequestType' in event and event['RequestType'] != 'Create':
        sendResponse(event, context,'SUCCESS', {})
        return
    
    logger.info(json.dumps(event))
    event_payload = event["ResourceProperties"]
    instance_type = event_payload['InstanceType']
    term_type = event_payload['TermType']
    operating_system = event_payload['OperatingSystem']
    hours_left = hours_left_for_current_month()
    next_month_hrs = hours_for_next_month()
    logger.info("# of Hrs left for this month {}".format(hours_left))
    unit_price = getPrice_from_API(operating_system, instance_type, region, term_type)
    logger.info("Unit Price {}".format(unit_price))
    monthly_price = hours_left * unit_price
    monthly_avg = 31 * 24 * unit_price
    next_month_price = next_month_hrs * unit_price
    logger.info("Monthly Price: {}".format(monthly_price))
    result = {
        'Pricing': {
                'OperatingSystem': operating_system,
                'TermType': term_type,
                'InstanceType': instance_type,
                'UnitPrice': unit_price,
                'EstCurrMonthPrice': monthly_price,
                '31DayPrice': monthly_avg,
                'NextMonthPrice': next_month_price,
                'HoursLeftInCurrMonth': hours_left,
                'ResponseTime': str(datetime.datetime.utcnow())
            }
    }
    sendResponse(event, context,'SUCCESS', result)
    return result
    # instCost = Decimal(str(round(Decimal(getHoursLeft()*instCost),2)))

# Get total # of hrs for next month
def hours_for_next_month():
    now = datetime.datetime.utcnow()
    month = now.month
    year = now.year
    nextmonth = (month + 1) % 12
    if month == 12:
        year = year + 1
    return calendar.monthrange(year, nextmonth)[1] * 24

# Get total # of hrs left in current month
def hours_left_for_current_month():
    now = datetime.datetime.utcnow()
    total_hours_in_cur_month = calendar.monthrange(now.year,now.month)[1] * 24
    hours_consumed_in_cur_month = ((now.day-1) * 24) + now.hour
    hours_left = total_hours_in_cur_month - hours_consumed_in_cur_month
    return hours_left

# Get region code
def region_lookup(region):
    if 'us-west-1' in region.lower():
        return "US West (N. California)"
    elif 'us-west-2' in region.lower():
        return "US West (Oregon)"
    elif 'us-east-1' in region.lower():
        return "US East (N. Virginia)"
    elif 'us-east-2' in region.lower():
        return "US East (Ohio)"
    elif 'ca-central-1' in region.lower():
        return "Canada (Central)"
    elif 'ap-south-1' in region.lower():
        return "Asia Pacific (Mumbai)"
    elif 'ap-northeast-2' in region.lower():
        return "Asia Pacific (Seoul)"
    elif 'ap-southeast-1' in region.lower():
        return "Asia Pacific (Singapore)"
    elif 'ap-southeast-2' in region.lower():
        return "Asia Pacific (Sydney)"
    elif 'ap-northeast-1' in region.lower():
        return "Asia Pacific (Tokyo)"
    elif 'eu-central-1' in region.lower():
        return "EU (Frankfurt)"
    elif 'eu-west-1' in region.lower():
        return "EU (Ireland)"
    elif 'eu-west-2' in region.lower():
        return "EU (London)"
    elif 'sa-east-1' in region.lower():
        return "South America (Sao Paulo)"
    elif 'us-gov-west-1' in region.lower():
        return "GovCloud (US)"
    return "Region Not Found"
# Send response back to CFN hook about the status of the function
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
                        data=json.dumps(response_body, use_decimal=True))
        return True
    except Exception as e:
        logger.info("Failed executing HTTP request: {}".format(e))
    return False
# Function to get the price of the EC2 Instance
def getPrice_from_API(oper_sys, instance_type, region, term_type):
    try:
        pricing = boto3.client('pricing', region_name='us-east-1')
        logger.info("instance: {}".format(instance_type))
        searchFilters=[                    
                {
                    'Type':'TERM_MATCH',
                    'Field':'tenancy',
                    'Value':'Shared'
                },
                {
                    'Type':'TERM_MATCH',
                    'Field':'location',
                    'Value':region_lookup(region)
                },
                {
                    'Type':'TERM_MATCH',
                    'Field':'operatingSystem',
                    'Value':oper_sys
                },
                {
                    'Type':'TERM_MATCH',
                    'Field':'preInstalledSw',
                    'Value':'NA'
                },
                {
                    'Type':'TERM_MATCH',
                    'Field':'termType',
                    'Value': term_type
                },
                {'Type' :'TERM_MATCH', 'Field':'capacityStatus', 'Value':'Used'},
                {
                    'Type':'TERM_MATCH',
                    'Field':'instanceType',
                    'Value': instance_type
                }
        ]
        #windows adds an extra license filter
        if 'Windows' in oper_sys:
            searchFilters.append({"Type":"TERM_MATCH", "Field": "licenseModel", "Value": "No License required"})
        response = pricing.get_products(
            ServiceCode='AmazonEC2',        # required
            Filters = searchFilters,
            FormatVersion='aws_v1',        # optional
            NextToken='',                  # optional
            MaxResults=20                   # optional
        )
        if len(response['PriceList']) > 1 :
            logger.info("Pricing list has more than one entry, considering first entry")
        elif len(response['PriceList']) == 0 :
            logger.info("Couldn't query pricing with given filters")
        resp_json = json.loads(response['PriceList'][0])
        price = 0
        for key, value in resp_json['terms'][term_type].items():
            logger.info("Reading Price for termType {}, key {}".format(term_type,key))
            for dimkey, dimValue in value['priceDimensions'].items():
                logger.info("Reading Price for dimension key {}".format(dimkey))
                price = dimValue['pricePerUnit']['USD']
        return Decimal(price)
    except Exception as e:
        print(e)
        raise e