import boto3
import logging
from datetime import datetime, timezone, timedelta
import os


# Initialize AWS SDK clients for EC2 and SNS
ec2 = boto3.client('ec2')
sns = boto3.client('sns')

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Retrieve configuration from environment variables
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
GRACE_PERIOD_MINUTES = int(os.environ.get('GRACE_PERIOD_MINUTES'))


def parse_ttl(ttl_string):
    """
    Helper function to safely parse a UTC timestamp from the TTL tag.
    """
    if not ttl_string:
        return None
    
    ttl_string = ttl_string.strip()
    
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            # Приводим распаршенное время к UTC
            dt = datetime.strptime(ttl_string, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
            
    logger.warning(f"Failed to parse TTL timestamp string: '{ttl_string}'")
    return None


def is_past_grace_period(launch_time):
    """
    Checks whether the configured Grace Period has elapsed since the instance launch time.
    Prevents race conditions on freshly launched instances.
    """
    if not launch_time:
        return True

    now = datetime.now(timezone.utc)
    return (now - launch_time) >= timedelta(minutes=GRACE_PERIOD_MINUTES)


def send_sns_alert(stopped_instances):
    """
    Helper function to publish execution results to Amazon SNS topic.
    """
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN is not set. Notification skipped.")
        return

    message_text = f"🚨 Cloud Janitor Alert: Stopped non-compliant EC2 instances: {', '.join(stopped_instances)}"
    
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message_text,
            Subject="CloudJanitor Alert: Instances Stopped"
        )
        logger.info(f"Successfully published notification to SNS Topic: {SNS_TOPIC_ARN}")
    except Exception as sns_err:
        logger.error(f"Failed to publish notification to SNS: {str(sns_err)}")


def lambda_handler(event, context):
    try:
        # 1. Configure filter to query only active running EC2 instances
        filters = [
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]

        # Use boto3 paginator to handle large-scale EC2 inventories seamlessly
        paginator = ec2.get_paginator('describe_instances')
        page_iterator = paginator.paginate(Filters=filters)

        now_utc = datetime.now(timezone.utc)

        instances_missing_ttl = []
        instances_expired_ttl = []

        for page in page_iterator:
            for reservation in page.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_id = instance.get('InstanceId')
                    launch_time = instance.get('LaunchTime')

                    if not instance_id:
                        continue

                    tags = {t['Key']: t['Value'] for t in instance.get('Tags', [])}
                    janitor_status = tags.get('Janitor_Status')
                    ttl_value = tags.get('TTL')

                    # Condition 1: Previously flagged for missing TTL tag
                    if janitor_status == 'Missing_TTL_Warning':
                        # Verify grace period to protect newly launched resources
                        if is_past_grace_period(launch_time):
                            logger.info(f"Instance {instance_id} is past grace period and has no TTL. Stopping it.")
                            instances_missing_ttl.append(instance_id)
                        else:
                            logger.info(f"Skipping {instance_id}: within Grace Period.")
                        continue

                    # Condition 2: Resource has a TTL tag — verify expiration
                    if ttl_value:
                        ttl_datetime = parse_ttl(ttl_value)
                        if ttl_datetime and ttl_datetime < now_utc:
                            logger.info(f"Instance {instance_id} expired! TTL: {ttl_datetime} < Current: {now_utc}")
                            instances_expired_ttl.append(instance_id)


        all_instances_to_stop = instances_missing_ttl + instances_expired_ttl

        if not all_instances_to_stop:
            logger.info("No non-compliant instances found. Cloud environment is clean.")
            return {'statusCode': 200, 'body': 'No instances to stop'}

        logger.info(f"Stopping non-compliant instances (Total {len(all_instances_to_stop)}): {all_instances_to_stop}")
        ec2.stop_instances(InstanceIds=all_instances_to_stop)  

        # Apply status tags for compliance tracking
        if instances_missing_ttl:
            ec2.create_tags(
                Resources=instances_missing_ttl,
                Tags=[{'Key': 'Janitor_Status', 'Value': 'Stopped_No_TTL'}]
            )

        if instances_expired_ttl:
            ec2.create_tags(
                Resources=instances_expired_ttl,
                Tags=[{'Key': 'Janitor_Status', 'Value': 'Stopped_TTL_Expired'}]
            )
        logger.info(f"Successfully tagged stopped instances: {all_instances_to_stop}")
        
        # Send notification alert to SNS
        send_sns_alert(all_instances_to_stop)

    except Exception as e:
        logger.error(f"Error processing event: {str(e)}")
        raise e

    return {
        'statusCode': 200,
        'body': f'Stopped {len(all_instances_to_stop)} instances.'
    }