# Welcome to AWS Cost Control Approval Workflow Project

This is a sample project to demonstrate the solution that allows organizations to proactively save cost by keeping the monthly expense with a certain threshold. Users requests AWS resources via AWS Service Catalog, the requested AWS resources are deployed only if their monthly cost is within the pre-approved budget, if monthly cost exceeds the pre-approved budget, an approval workflow is triggered to a pre-configured adminstrator.

This project uses combination of AWS Service Catalog along with AWS CloudFormation resources like `WaitCondition`, `WaitHandle` and Custom Resources to trigger an approval workflow. Based on the workflow outcome, either the CloudFormation stack is deployed or rolledback. This project uses its own internal ledger to keep track of approved, rejected and forecasted spend of AWS resources relying on AWS Budgets & AWS Pricing APIs. These internal ledgers are updated at periodic intervals to align with AWS Budgets dashboard and are reset at beginning of every calendar month.

## Examples

| # | Description                                       | Requested Cost | Monthly Budget | Available Budget | Request Status                      |
|---|---------------------------------------------------|:--------------:|:--------------:|:----------------:|-------------------------------------|
| 1 | Request # 1 - AWS resources costing $10 per month | 10             | 100            | 20               | Auto Approved by the system         |
| 2 | Request # 2 - AWS resources costing $30 per month | 30             | 100            | 20               | Pending for administrator approval  |
| 3 | Request # 3 - AWS resources costing $15 per month | 15             | 100            | 20               | Blocked for decision on Request # 2 |

## High Level Architecture

![Cost Control Approval Workflow Architecture](./architecture.png)

1. User launches a product (ex. Amazon Linux EC2) from Service Catalog.
2. Associated CloudFormation template has a `WaitCondition`, `WaitHandle` and custom resources (`linux-ami-lookup`, `get-ec2-pricing` & `save-request`) which determines the AMI ID  (based on the user inputs caputured in Service Catalog Launch Product form), estimated price of the requested InstanceType.
3. A CloudFormation custom resource (`save-request`) saves the metadata of product request, AMI information and pricing information to a DynamoDB table.
4. Cloudwatch Rule invokes `process-requests` Lambda every 5 mins (configurable in `template.yaml`). `process-requests` Lambda looks for saved/pending/blocked requests and routes the request (if requested cost is greater than available budget) to approver(s) based on configuration stored in the DynamoDB table. if requested cost is within the available budget, the request is auto approved and the CloudFormation template is deployed.
5. Amazon Simple Notification Service configured to sends email notifications with links to approve/reject a request to all subscribers (administrators) of the SNS topic. (i.e., If cost is going to exceed the pre-approved budget then email is triggered)
6. Administrator reviews the email and acts on the request by clicking Approve/Reject url links received in the email. Note: Ignoring the request for 12 hrs will automatically revoke the CloudFormation template.
7. Approving/Rejecting a request invokes a REST API backed by Lambda `approve-request`.
8. `approve-request` Lambda submits a POST request to respective CloudFormation `WaitHandle` url to resume the deployment of stack or rollback the stack. Lambda also updates the status in DynamoDB accordingly.
9. Once CloudFormation template is deployed/rollback, product launch request status is updated accordingly in Service Catalog.
10. Whenever Cost & Usage Report update is available, the report is stored in configured S3 Bucket. This Bucket is configured to trigger `rebase-budgets` Lambda, which in turn resets `budgetLimit`, `forecastedSpend` & `actualSpend` for every Business Entity in DynamoDB database
11. At the begining of every month, a CloudWatch Rule triggers `rebase-budgets` Lambda, which in turn resets `accruedApprovedSpend` for every Business Entity in DynamoDB database

## Project Structure

This project contains source code and supporting files for a serverless application that you can deploy with the SAM CLI. It includes the following files and folders.

- `save-request` - A Lambda functions which records the user's launch request in DynamoDB table.
- `process-requests` - A Lambda function triggered by CloudWatch Rule at a pre-configured interval (default 5 mins). This Lambda is responsible for processing the requests that are in SAVED, PENDING & BLOCKED states. This Lambda also keeps track of internal ledgers and constantly re-evaluates the requests.
- `approve-request` - A Lambda function used by the API Gateway to handle the requests when an Administrator approves/rejects the request using the links available in email notification.
- `rebase-budgets` - A Lambda function that gets triggered in 2 different scenarios, whenever AWS CUR (Cost & Usage Reports) update is available or at the beginning of every calendar month. This Lambda is responsible to update the Master data with latest Budget Limits, Actual Spends and Forecasted Spend for a particular month. This Lambda is also responsible to reset the internal ledgers at beginning of each month.
- `linux-ami-lookup` - A Generic Lambda function used to get the ami-id of Linux EC2 instance based on the inputs selected by the user.
- `get-ec2-pricing` - A Generic Lambda function used to calculate the price of an EC2 instance based on the inputs selected by the user.
- `ec2_approval_template.yaml` - A sample CloudFormation template that can be used to configure a sample Service Catalog Product.
- `template.yaml` - A template that defines the application's AWS resources.
- `master_data.py` - Sample master data that needs to be loaded to DynamoDB table.

## Database

- DynamoDB table uses 2 partitions
  - BUDGET - used to represent metadata of a Business Entity
  - REQUEST - used to represent a Service Catalog Product Launch request
- `budgetLimit` - Budget Limit for specific Business Entity maintained by the AWS Budgets Dashboard. Updated by `rebase-budgets` whenever there is a CUR data refersh.
- `actualSpend` - Acutal Spend for specific Business Entity maintained by the AWS Budgets Dashboard. Updated by `rebase-budgets` whenever there is a CUR data refersh.
- `forecastedSpend` - Forecasted Spend for specific Business Entity maintained by the AWS Budgets Dashboard. Updated by `rebase-budgets` whenever there is a CUR data refersh.
- `accruedForecastedSpend` - Internally maintained ledger spend that stores the accruals of forecasted spend before Cost & Usage data udpate is available. This is managed by `process-requests` Lambda.
- `accruedBlockedSpend` - Internally maintained ledger spend that stores the accruals of each requested product per Business Entity. Reset whenever a request is rejected.
- `accruedApprovedSpend` - Internally maintained ledger spend that stores the accruals of each approved request per Business Entity. This is reset at begining of every calendar month by `rebase-budgets` Lambda.

## Prerequisites

- Create a Fixed Monthly Budget in AWS Budgets
- Cost & Usage Reports Enabled in AWS Budgets

## Deploying the Project

### 1. Deploy SAM application

The Serverless Application Model Command Line Interface (SAM CLI) is an extension of the AWS CLI that adds functionality for building and testing Lambda applications. It uses Docker to run your functions in an Amazon Linux environment that matches Lambda. It can also emulate your application's build environment and API.

To use the SAM CLI, you need the following tools.

- SAM CLI - [Install the SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
- [Python 3 installed](https://www.python.org/downloads/)
- Docker - [Install Docker community edition](https://hub.docker.com/search/?type=edition&offering=community)

To build and deploy your application for the first time, run the following in your shell:

```bash
sam build --use-container
sam deploy --guided
```

The first command will build the source of your application. The second command will package and deploy your application to AWS, with a series of prompts:

- **Stack Name**: The name of the stack to deploy to CloudFormation. This should be unique to your account and region, and a good starting point would be something matching your project name.
- **AWS Region**: The AWS region you want to deploy your app to.
- **ResourcePrefix**: A string that is used to prefix all AWS resources provisioned by this application.
- **Confirm changes before deploy**: If set to yes, any change sets will be shown to you before execution for manual review. If set to no, the AWS SAM CLI will automatically deploy application changes.
- **Allow SAM CLI IAM role creation**: Many AWS SAM templates, including this example, create AWS IAM roles required for the AWS Lambda function(s) included to access AWS services. By default, these are scoped down to minimum required permissions. To deploy an AWS CloudFormation stack which creates or modified IAM roles, the `CAPABILITY_NAMED_IAM` value for `capabilities` must be provided. If permission isn't provided through this prompt, to deploy this example you must explicitly pass `--capabilities CAPABILITY_NAMED_IAM` to the `sam deploy` command.
- **Save arguments to samconfig.toml**: If set to yes, your choices will be saved to a configuration file inside the project, so that in the future you can just re-run `sam deploy` without parameters to deploy changes to your application.

**Note:** Make sure to save the CloudFormation Outputs, you will need these in next steps.

### 2. Setup Amazon Simple Notification Service Topic

For each business entity you would like to setup in the system, create a SNS topic and a email subscription to the topic with adminstrator's email address.

[SNS documentation to create a SNS topic](https://docs.aws.amazon.com/sns/latest/dg/sns-tutorial-create-topic.html)

### 3. Load Master Data

Update the name of the DynamoDB table in `master_data.py` file created in [Step 1.](#1-deploy-sam-application) You will find the name of the table as Cloudformatin outputs from deployed stack.

For each business entity you would like to setup in the system, make an entry in `budgets` array in `master_data.py` file.

JSON Object structure -

```python
{
  "partitionKey": "BUDGET",
  "rangeKey": str(uuid.uuid4()),
  "budgetName": "<name-of-the-budget-as-listed-in-the-AWS-Budgets-dashboard-supports-only-fixed-monthly-budget-type>",
  "budgetLimit": 123 # Update it with Budget Limit shown in the AWS Budgets Dashboard
  "actualSpend": 123 # Update it with Budget Actual Spend shown in the AWS Budget Dashboard
  "forecastedSpend": 123 # Update it with Forecasted Spend shown in the AWS Budget Dashboard
  "approverEmail": "<email-address-of-the-approver-for-specified-business-entity>",
  "notifySNSTopic": "<sns-topic-created-in-Step-2-for-specified-business-entity>",
  "accruedForecastedSpend": 0,
  "accruedBlockedSpend": 0,
  "accruedApprovedSpend": 0,
  "businessEntity": "<name-of-the-business-entity>",
  "budgetForecastProcessed": False,
  "budgetUpdatedAt": str(datetime.datetime.utcnow())
}
```

Once all the above placeholders is updated in  `master_data.py` file, run the file from a terminal window.

### 4. Setup Portfolio & Product in Service Catalog

#### 4.1. Refer following link to create a sample Service Catalog Portfolio & Product

[Service Catalog Create Portfolio & Product (Refer Step 3 & Step 4)](https://docs.aws.amazon.com/servicecatalog/latest/adminguide/getstarted.html)

While setting up the sample product, use the `ec2_approval_template.yaml` to setup the product.

**Note:** Make sure to update the CloudFormation custom resources (`SaveRequestFunction`, `GetAMIInfo` & `GetEC2PricingInfo`) `ServiceToken` attribute. `ServiceToken` in the `ec2_approvaal_template.yaml` is configured to import outputs from the stack deployed in [Step 1](#1-deploy-sam-application).

Following Import keys needs to be udpated in `ec2_approval_template.yaml` file -

- `<name-of-stack-deployed-in-step-1>-SaveRequestLambda`
- `<name-of-stack-deployed-in-step-1>-LinuxAMILookupLambda`
- `<name-of-stack-deployed-in-step-1>-EC2PricingLambda`

#### 4.2. Refer following link to create a Launch Constraint

[Service Catalog Add a Launch Constraint (Refer Step 6)](https://docs.aws.amazon.com/servicecatalog/latest/adminguide/getstarted-launchconstraint.html)

Navigate to Portfolio created in [Step 4.1](#41-refer-following-link-to-create-a-sample-service-catalog-portfolio--product) and create a Launch Constraint for Product created in [Step 4.1](#41-refer-following-link-to-create-a-sample-service-catalog-portfolio--product). Select IAM role created in [Step 1](#1-deploy-sam-application). Use CloudFormation Outputs `LaunchConstraintIAMRoleARN`

### 5. Create Cost & Usage Report in AWS Budgets

**Note** Use the name of the S3 Bucket (Refer CloudFormation Outputs `CURBucketName`) created in [Step 1](#1-deploy-sam-application) to configure Cost & Usage Report. This report uploads to S3 Bucket and acts as a trigger to update the internal ledger maintained by the system.

[Cost & Usage Report Creation Documentation](https://docs.aws.amazon.com/cur/latest/userguide/cur-create.html)

## Limitations

- Internally maintained ledger for each Business Entity is not updated when a product is terminated in Service Catalog.
- EBS volume pricing is not considered in the workflow.
- User is not notified about the status of the launched Product.
- Supports only Fixed Monthly Budget.

## Cleanup

To delete the sample project that you created, use the AWS CLI. Assuming you used your project name for the stack name, you can run the following:

```bash
aws CloudFormation delete-stack --stack-name "<name-of-the-stack-deployed-in-step-1>"
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

## Resources

See the [AWS SAM developer guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html) for an introduction to SAM specification, the SAM CLI, and serverless application concepts.

See the [AWS Service Catalog](https://docs.aws.amazon.com/servicecatalog/latest/adminguide/introduction.html) for introduction to Service Catalog.

See the [AWS Cloudformation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/Welcome.html) for introduction to CloudFormation.