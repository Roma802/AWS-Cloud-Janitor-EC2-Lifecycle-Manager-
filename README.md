# AWS Cloud Janitor EC2 Lifecycle Manager 

Event-driven serverless architecture for automated EC2 instance lifecycle management and cost optimization using AWS Lambda, EventBridge, Amazon SNS, and Telegram.

## Architecture

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer / Engineer
    participant EC2 as Amazon EC2
    participant EB as EventBridge (Cron / Event)
    participant Tagger as Lambda (CloudJanitor-Tagger)
    participant AutoStop as Lambda (CloudJanitor-AutoStop)
    participant SNS as Amazon SNS (CloudJanitor-Alerts)
    participant Forwarder as Lambda (TelegramForwarder)
    actor TG as Telegram Chat

    box 1. Detection & Tagging
        participant EB
        participant Tagger
        participant EC2
    end

    box 2. Notification Pipeline
        participant SNS
        participant Forwarder
        participant TG
    end

    box 3. Automated Enforcing
        participant AutoStop
    end

    %% Flow 1: Detection & Warning
    EB->>Tagger: Scheduled Trigger (Hourly Cron)
    Tagger->>EC2: Describe Instances (State = running)
    EC2-->>Tagger: Return running instances & tags
    Note over Tagger: Check Grace Period (>30m)<br/>& Missing 'TTL' tag
    Tagger->>EC2: CreateTags (Janitor_Status = Missing_TTL_Warning)
    Tagger->>SNS: Publish Warning Message (Subject & Instances)
    SNS->>Forwarder: Trigger via SNS Subscription
    Forwarder->>TG: Send Telegram Alert (HTML Format)

    %% Flow 2: Automated Cleanup
    EB->>AutoStop: Scheduled Trigger (Cleanup Cron)
    AutoStop->>EC2: Describe Instances (Running & Warnings/Expired)
    EC2-->>AutoStop: Return non-compliant instances
    Note over AutoStop: Parse TTL & verify Grace Period
    AutoStop->>EC2: Stop Instances (Batch / Individual Fallback)
    AutoStop->>EC2: CreateTags (Janitor_Status = Stopped_No_TTL / Stopped_TTL_Expired)
    AutoStop->>SNS: Publish Execution Alert
    SNS->>Forwarder: Trigger via SNS Subscription
    Forwarder->>TG: Send Telegram Alert (HTML Format)
