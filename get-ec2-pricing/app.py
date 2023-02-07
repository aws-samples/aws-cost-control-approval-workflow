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
import calendar
import datetime
import logging
import os
from decimal import Decimal

import boto3
import requests
import simplejson as json

logger = logging.getLogger()
logger.setLevel(logging.INFO)
region = os.environ['AWS_REGION']


def lambda_handler(event, context):
    # Do not do anything for CFN Update and Delete
    if 'RequestType' in event and event['RequestType'] != 'Create':
        send_response(event, context, 'SUCCESS', {})
        return

    logger.info(json.dumps(event))
    event_payload = event["ResourceProperties"]
    instance_type = event_payload['InstanceType']
    term_type = event_payload['TermType']
    operating_system = event_payload['OperatingSystem']
    hours_left = hours_left_for_current_month()
    next_month_hrs = hours_for_next_month()
    logger.info("# of Hrs left for this month {}".format(hours_left))
    unit_price = get_price_from_api(operating_system, instance_type, region, term_type)
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
            'ResponseTime': str(datetime.datetime.utcnow()),
        }
    }
    send_response(event, context, 'SUCCESS', result)
    return result
    # instCost = Decimal(str(round(Decimal(getHoursLeft()*instCost),2)))


# Get total # of hrs for next month
def hours_for_next_month():
    now = datetime.datetime.utcnow()
    month = now.month
    year = now.year
    next_month = month + 1
    if month == 12:
        year = year + 1
    if next_month > 12:
        next_month = next_month % 12
    return calendar.monthrange(year, next_month)[1] * 24


# Get total # of hrs left in current month
def hours_left_for_current_month():
    now = datetime.datetime.utcnow()
    total_hours_in_cur_month = calendar.monthrange(now.year, now.month)[1] * 24
    hours_consumed_in_cur_month = ((now.day - 1) * 24) + now.hour
    hours_left = total_hours_in_cur_month - hours_consumed_in_cur_month
    return hours_left


# Get region code
def region_lookup(region_name):
    lookup = {
        'us-west-1': "US West (N. California)",
        'us-west-2': "US West (Oregon)",
        'us-east-1': "US East (N. Virginia)",
        'us-east-2': "US East (Ohio)",
        'ca-central-1': "Canada (Central)",
        'ap-south-1': "Asia Pacific (Mumbai)",
        'ap-northeast-2': "Asia Pacific (Seoul)",
        'ap-southeast-1': "Asia Pacific (Singapore)",
        'ap-southeast-2': "Asia Pacific (Sydney)",
        'ap-northeast-1': "Asia Pacific (Tokyo)",
        'eu-central-1': "EU (Frankfurt)",
        'eu-west-1': "EU (Ireland)",
        'eu-west-2': "EU (London)",
        'sa-east-1': "South America (Sao Paulo)",
        'us-gov-west-1': "GovCloud (US)",
    }
    return lookup.get(region_name.lower(), "Region Not Found")


# Send response back to CFN hook about the status of the function
def send_response(event, context, response_status, response_data):
    response_body = {
        'Status': response_status,
        'Reason': 'See the details in CloudWatch Log Stream ' + context.log_stream_name,
        'PhysicalResourceId': context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': response_data,
    }
    try:
        response = requests.put(event['ResponseURL'], data=json.dumps(response_body, use_decimal=True))
        return True
    except Exception as e:
        logger.info("Failed executing HTTP request: {}".format(e))
    return False


# Function to get the price of the EC2 Instance
def get_price_from_api(oper_sys, instance_type, region_name, term_type):
    try:
        pricing = boto3.client('pricing', region_name='us-east-1')
        logger.info("instance: {}".format(instance_type))
        search_filters = [
            {
                'Type': 'TERM_MATCH',
                'Field': 'tenancy',
                'Value': 'Shared'
            },
            {
                'Type': 'TERM_MATCH',
                'Field': 'location',
                'Value': region_lookup(region_name)
            },
            {
                'Type': 'TERM_MATCH',
                'Field': 'operatingSystem',
                'Value': oper_sys
            },
            {
                'Type': 'TERM_MATCH',
                'Field': 'preInstalledSw',
                'Value': 'NA'
            },
            {
                'Type': 'TERM_MATCH',
                'Field': 'termType',
                'Value': term_type
            },
            {'Type': 'TERM_MATCH', 'Field': 'capacityStatus', 'Value': 'Used'},
            {
                'Type': 'TERM_MATCH',
                'Field': 'instanceType',
                'Value': instance_type
            }
        ]
        # windows adds an extra license filter
        if 'Windows' in oper_sys:
            search_filters.append({"Type": "TERM_MATCH", "Field": "licenseModel", "Value": "No License required"})
        response = pricing.get_products(
            ServiceCode='AmazonEC2',  # required
            Filters=search_filters,
            FormatVersion='aws_v1',  # optional
            NextToken='',  # optional
            MaxResults=20  # optional
        )
        if len(response['PriceList']) > 1:
            logger.info("Pricing list has more than one entry, considering first entry")
        elif len(response['PriceList']) == 0:
            logger.info("Couldn't query pricing with given filters")
        resp_json = json.loads(response['PriceList'][0])
        price = 0
        for key, value in resp_json['terms'][term_type].items():
            logger.info("Reading Price for termType {}, key {}".format(term_type, key))
            for dim_key, dim_value in value['priceDimensions'].items():
                logger.info("Reading Price for dimension key {}".format(dim_key))
                price = dim_value['pricePerUnit']['USD']
        return Decimal(price)
    except Exception as e:
        print(e)
        raise e
