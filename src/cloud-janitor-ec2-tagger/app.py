import boto3
import os
import logging
from botocore.exceptions import ClientError

# Initialize AWS SDK clients for EC2 and SNS
ec2 = boto3.client('ec2')
sns = boto3.client('sns')

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Retrieve configuration from environment variables
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')

def send_warning_sns(instances_to_warn):
    """
    Publishes a warning notification to Amazon SNS,
    which will be picked up and forwarded to Telegram by the telegramforwarder function.
    """
    if not SNS_TOPIC_ARN or not instances_to_warn:
        logger.info("Skipping SNS alert: SNS_TOPIC_ARN is not set or instances list is empty.")
        return

    # Format instance list into bullet points for readable notification layout
    formatted_instances = '\n'.join([f"• {i}" for i in instances_to_warn])

    subject = "⚠️ Cloud Janitor: Missing TTL Warning"
    message = (
        f"The following EC2 instances are missing the required 'TTL' tag:\n\n"
        f"{formatted_instances}\n\n"
        f"Please set a 'TTL' tag (example: 2026-10-01). "
        f"Otherwise, they will be automatically stopped!"
    )

    try:
        # Publish notification payload to SNS
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject,  
        )
        logger.info(
            f"Successfully published warning to SNS for instances: {instances_to_warn}"
        )
    except Exception as e:
        logger.error(f"Failed to publish warning to SNS: {str(e)}")


def lambda_handler(event, context):
    try:
        # 1. Extract EC2 instance IDs from the incoming CloudTrail event
        detail = event.get('detail') or {}
        response_elements = detail.get('responseElements') or {}
        instances_set = response_elements.get('instancesSet') or {}
        items = instances_set.get('items') or []  
        
        # Parse non-empty instance IDs
        instance_ids = [
            item['instanceId']
            for item in items 
            if item and item.get('instanceId')]
        
        if not instance_ids:
            logger.info("No instance IDs found in the event.")
            return {'statusCode': 200, 'body': 'No instances to process'}

        instances_to_tag = []
        
        # 2. Fetch active instance details and current tags from EC2 API
        response = ec2.describe_instances(InstanceIds=instance_ids)
        
        # Flatten instance items from EC2 Reservations response
        instances = [
            inst
            for res in (response.get('Reservations') or [])
            for inst in (res.get('Instances') or [])
            if inst and inst.get('InstanceId')
        ]

        if not instances:
            logger.info("No active instances returned from EC2 describe call.")
            return {'statusCode': 200, 'body': 'No valid instances found'}

        # 3. Evaluate each instance for mandatory 'TTL' tag compliance
        for instance in instances:
            instance_id = instance['InstanceId']
            logger.info(f"Processing instance: {instance_id}")

            # Map EC2 tag key-value pairs into a dictionary for easy lookup
            tag_dict = {tag['Key']: tag['Value'] for tag in (instance.get('Tags') or [])}
            if 'TTL' not in tag_dict:
                logger.warning(f"Instance {instance_id} is missing TTL tag!")
                instances_to_tag.append(instance_id)
            else:
                logger.info(f"Instance {instance_id} has TTL: {tag_dict['TTL']}")

        # 4. Mark non-compliant instances and send warning alert
        if instances_to_tag:
            ec2.create_tags(
                Resources=instances_to_tag,
                Tags=[{
                    'Key': 'Janitor_Status',
                    'Value': 'Missing_TTL_Warning'
                }]
            )
            logger.info(f"Successfully tagged instances for review: {instances_to_tag}")
            send_warning_sns(instances_to_tag)
            
    except Exception as e:
        logger.error(f"Error processing event: {str(e)}")
        raise e

    return {'statusCode': 200, 'body': 'Check complete'}