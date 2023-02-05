/* 
 * MIT No Attribution
 * 
 * Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * 
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this
 * software and associated documentation files (the "Software"), to deal in the Software
 * without restriction, including without limitation the rights to use, copy, modify,
 * merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
 * INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
 * OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
// Map instance architectures to an AMI name pattern
var archToAMINamePattern = {
    "PV64": "amzn-ami-pv*x86_64-ebs",
    "HVM64": "amzn-ami-hvm*x86_64-gp2",
    "HVMG2": "amzn-ami-graphics-hvm*x86_64-ebs*"
};
var aws = require("aws-sdk");

exports.handler = function(event, context) {

    console.log("REQUEST RECEIVED:\n" + JSON.stringify(event));
    
    // For Delete requests, immediately send a SUCCESS response.
    if (event.RequestType == "Delete") {
        sendResponse(event, context, "SUCCESS");
        return;
    }

    var responseStatus = "FAILED";
    var responseData = {};

    var ec2 = new aws.EC2({region: process.env.AWS_REGION});
    var describeImagesParams = {
        Filters: [{ Name: "name", Values: [archToAMINamePattern[event.ResourceProperties.Architecture]]}],
        Owners: [event.ResourceProperties.Architecture == "HVMG2" ? "679593333241" : "amazon"]
    };

    // Get AMI IDs with the specified name pattern and owner
    ec2.describeImages(describeImagesParams, function(err, describeImagesResult) {
        if (err) {
            responseData = {Error: "DescribeImages call failed"};
            console.log(responseData.Error + ":\n", err);
        }
        else {
            var images = describeImagesResult.Images;
            // Sort images by name in decscending order. The names contain the AMI version, formatted as YYYY.MM.Ver.
            images.sort(function(x, y) { return y.Name.localeCompare(x.Name); });
            for (var j = 0; j < images.length; j++) {
                if (isBeta(images[j].Name)) continue;
                responseStatus = "SUCCESS";
                responseData["Id"] = images[j].ImageId;
                responseData["Volumes"] = images[j].BlockDeviceMappings;
                break;
            }
        }
        console.log("Response Data: "+JSON.stringify(responseData));
        sendResponse(event, context, responseStatus, responseData);
    });
};
// Check if the image is a beta or rc image. The Lambda function won't return any of those images.
function isBeta(imageName) {
    return imageName.toLowerCase().indexOf("beta") > -1 || imageName.toLowerCase().indexOf(".rc") > -1;
}
// Send response to the pre-signed S3 URL 
function sendResponse(event, context, responseStatus, responseData) {
    var responseBody = JSON.stringify({
        Status: responseStatus,
        Reason: "See the details in CloudWatch Log Stream: " + context.logStreamName,
        PhysicalResourceId: context.logStreamName,
        StackId: event.StackId,
        RequestId: event.RequestId,
        LogicalResourceId: event.LogicalResourceId,
        Data: responseData
    });

    console.log("RESPONSE BODY:\n", responseBody);

    var https = require("https");
    var url = require("url");

    var parsedUrl = url.parse(event.ResponseURL);
    var options = {
        hostname: parsedUrl.hostname,
        port: 443,
        path: parsedUrl.path,
        method: "PUT",
        headers: {
            "content-type": "",
            "content-length": responseBody.length
        }
    };

    console.log("SENDING RESPONSE...\n");

    var request = https.request(options, function(response) {
        console.log("STATUS: " + response.statusCode);
        console.log("HEADERS: " + JSON.stringify(response.headers));
        // Tell AWS Lambda that the function execution is done  
        context.done();
    });

    request.on("error", function(error) {
        console.log("sendResponse Error:" + error);
        // Tell AWS Lambda that the function execution is done  
        context.done();
    });
  
    // write data to request body
    request.write(responseBody);
    request.end();
}