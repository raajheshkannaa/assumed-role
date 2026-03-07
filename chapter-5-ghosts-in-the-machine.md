# Chapter 5: Ghosts in the Machine

---

7:02 AM. Thursday.

I delete the replication rule. That's the immediate action — stop the bleeding.

```bash
aws s3api delete-bucket-replication \
    --bucket meridian-datalake-raw \
    --profile prod-datalake
```

This kills *all* replication rules — including the legitimate internal one. I know this. The legitimate replication to `meridian-datalake-replica` is now broken too. I make a note to restore it during containment. Right now, stopping the exfiltration matters more than data redundancy.

But "stop the bleeding" assumes you know where all the wounds are. I'm learning — slowly, painfully — that every time I think I've found the extent of this compromise, there's another layer.

I need to think bigger. Not reactive. Not "what did they just do." I need to ask: "What would I do if I were inside this environment and I wanted to survive getting caught?"

Persistence. That's the word that keeps echoing. Creating new credentials that survive the revocation of old ones. Backdoors that keep the door open even after you change the locks.

I run the query I should have run hours ago:

```sql
SELECT
    eventTime,
    eventName,
    recipientAccountId,
    requestParameters,
    responseElements,
    userIdentity.arn AS principalArn,
    sourceIPAddress
FROM
    event_data_store_id
WHERE
    eventTime > '2025-03-01T00:00:00Z'
    AND eventName IN ('CreateUser', 'CreateAccessKey', 'AttachUserPolicy', 'PutUserPolicy', 'CreateLoginProfile')
ORDER BY eventTime ASC
```

The results come back. Most are legitimate — service accounts created by Terraform, developers creating keys for CI/CD, my own activity setting up IAM users for vendor integrations.

But one entry freezes my blood.

```json
{
    "eventTime": "2025-03-10T14:22:08Z",
    "eventSource": "iam.amazonaws.com",
    "eventName": "CreateUser",
    "awsRegion": "us-east-1",
    "sourceIPAddress": "104.28.193.47",
    "userIdentity": {
        "type": "AssumedRole",
        "arn": "arn:aws:sts::192837465019:assumed-role/spoke-001/session-0310"
    },
    "requestParameters": {
        "userName": "svc-monitoring-agent"
    },
    "responseElements": {
        "user": {
            "userName": "svc-monitoring-agent",
            "userId": "AIDAEXAMPLE123456789",
            "arn": "arn:aws:iam::192837465019:user/svc-monitoring-agent",
            "createDate": "2025-03-10T14:22:08Z"
        }
    }
}
```

March 10th. Three days ago. Account `192837465019` — the security tooling account. *My* account. The one that runs my detection pipeline, my CloudTrail Lake queries, my EventBridge rules.

The attacker created a user called `svc-monitoring-agent` in my security tooling account. Three days ago. While I was doing my regular work, reviewing Prowler findings, fixing IAM permissions, living my normal life.

I check what they attached to it:

```json
{
    "eventTime": "2025-03-10T14:22:31Z",
    "eventSource": "iam.amazonaws.com",
    "eventName": "AttachUserPolicy",
    "requestParameters": {
        "userName": "svc-monitoring-agent",
        "policyArn": "arn:aws:iam::aws:policy/AdministratorAccess"
    }
}
```

`AdministratorAccess`. Full admin. In the security tooling account. The account that has cross-account read access to every other account for centralized monitoring.

And then the access key:

```json
{
    "eventTime": "2025-03-10T14:22:45Z",
    "eventSource": "iam.amazonaws.com",
    "eventName": "CreateAccessKey",
    "requestParameters": {
        "userName": "svc-monitoring-agent"
    },
    "responseElements": {
        "accessKey": {
            "userName": "svc-monitoring-agent",
            "accessKeyId": "AKIAZBEXAMPLE789",
            "status": "Active",
            "createDate": "2025-03-10T14:22:45Z"
        }
    }
}
```

A backdoor. Administrator access. In my security account. Created three days before they even triggered the `StopLogging` alert.

They've been inside longer than I thought. Much longer.

The `StopLogging` wasn't the beginning of the attack. It was a mid-game move. The beginning was two weeks ago, when they first used Marcus's key to map the environment. The backdoor was planted three days ago. The `StopLogging`, the SG change, the database queries — those were all after VEGA already had persistent admin access to the most sensitive account in the organization.

I want to throw up.

But it gets worse. Because I keep looking.

```sql
SELECT
    eventTime,
    eventName,
    requestParameters,
    recipientAccountId
FROM
    event_data_store_id
WHERE
    eventTime > '2025-03-10T00:00:00Z'
    AND recipientAccountId = '192837465019'
    AND eventName IN ('CreateFunction20150331', 'PutRule', 'PutTargets')
    AND userIdentity.arn LIKE '%svc-monitoring-agent%'
ORDER BY eventTime ASC
```

```json
{
    "eventTime": "2025-03-10T15:08:12Z",
    "eventSource": "lambda.amazonaws.com",
    "eventName": "CreateFunction20150331",
    "requestParameters": {
        "functionName": "monitoring-credential-refresh",
        "runtime": "python3.12",
        "handler": "lambda_function.lambda_handler",
        "role": "arn:aws:iam::192837465019:role/monitoring-lambda-role",
        "timeout": 30
    }
}
```

```json
{
    "eventTime": "2025-03-10T15:09:44Z",
    "eventSource": "events.amazonaws.com",
    "eventName": "PutRule",
    "requestParameters": {
        "name": "monitoring-refresh-schedule",
        "scheduleExpression": "rate(6 hours)",
        "state": "ENABLED"
    }
}
```

A Lambda function called `monitoring-credential-refresh` with an EventBridge rule triggering it every six hours. VEGA didn't just create a backdoor — he created a *self-healing* backdoor. A Lambda that refreshes its own credentials on a schedule, ensuring that even if someone deletes the access key, a new one gets created automatically.

He built automation inside my automation account. He used my own infrastructure pattern against me.

He'd built a program inside my own security account that automatically gave him fresh credentials every six hours. A self-healing backdoor.

---

7:31 AM. Thursday.

I run Prowler. Emergency mode, full assessment across all accounts. I should have done this hours ago. I should have done it weeks ago. But Prowler takes time on 45 accounts, and I'm one person, and there's always something more urgent.

The results for the IMDSv1 check come in:

```
CHECK: ec2_instance_imdsv2_enabled
SEVERITY: Critical
STATUS: FAIL (3 instances)
DETAILS:
  - i-0a1b2c3d4e5f6g7 (dev-platform-012) - HttpTokens: optional
  - i-0h8i9j0k1l2m3n4 (dev-platform-012) - HttpTokens: optional
  - i-0v2w3x4y5z6a7b8 (dev-platform-012) - HttpTokens: optional
```

Prowler flagged this three months ago. Check `ec2_instance_imdsv2_enabled`, critical severity. I marked it "acknowledged — will remediate next quarter."

There is no next quarter when someone's inside your network.

The attacker used the SSRF → IMDSv1 path — the same technique class that enabled the Capital One breach in 2019. Instance metadata service version 1 doesn't require a token for requests. If you can find any SSRF vulnerability in any application running on an IMDSv1 instance, you can grab the instance role credentials with a single HTTP request.

The tool worked. The tool has been working for three months. I didn't act on it.

I also run truffleHog across Meridian's GitHub repos:

```bash
trufflehog git https://github.com/meridian-financial/payment-service \
    --only-verified --json
```

Two more API keys. In old commit history. One for an SQS queue, one for a DynamoDB table. Both active. Both forgotten. The credentials were always leaking. I just wasn't looking.

---

8:15 AM. Thursday.

My detection pipeline didn't catch `CreateAccessKey`. It didn't catch `CreateUser` in the security tooling account. It didn't catch the Lambda creation.

Because I never wrote those detections.

I built detections for the dramatic stuff. `StopLogging` — the emergency alarm. Public S3 buckets — the headline grabber. `AuthorizeSecurityGroupIngress` with `0.0.0.0/0` — the open door. The things that scare you when you read about them on Twitter. The things that make the news.

But `CreateAccessKey`? That happens dozens of times a day in a 45-account organization. Developers creating keys for CI/CD, Terraform provisioning service accounts, automation creating temporary credentials. It's noise. It's the background radiation of a cloud environment.

Except when it's not.

I built walls around the castle and left the servants' entrance unlocked. No — worse. I built a wall checker that checks the walls, but I never told it to check the doors.

I sit on my bed. Laptop balanced on a pillow. The apartment smells like the chai I made at 5 AM and forgot to drink — cold now, a film on the surface. My mother would say I work too hard. She's right. She's been right every Sunday for two years.

The gap in my defenses isn't a technical failure. It's a *me* failure. I'm one person. I built what I could with the time I had. And what I built has holes because I'm human and humans have blind spots and no single person — no matter how skilled, no matter how dedicated, no matter how many 2 AM alerts they respond to — can see everything.

VEGA knew this. He studied my detections. He admired them, probably. And then he walked through the gaps between them.

---

9:02 AM. Thursday.

The logs tell a story when you read them chronologically. The original access key was created September 15, 2024. Marcus Chen's last week at Meridian was September 18-22, 2024. The key was created three days before his final week — he exported it to debug a weekend deployment issue and never deleted it.

I check Identity Center:

```bash
aws identitystore list-users \
    --identity-store-id d-9067642c99 \
    --filters "AttributePath=UserName,AttributeValue=mchen" \
    --profile management
```

```json
{
    "Users": []
}
```

Empty. His SSO user was properly deprovisioned on his last day. His Identity Center session was revoked. His Slack was deactivated. His GitHub access was removed. The offboarding checklist was followed. Every box was checked.

But the access key lived in a separate lifecycle. Identity Center governs federated access — SSO sessions, console login, short-lived credentials. Programmatic access keys belong to IAM users, which exist independently. You can revoke someone's SSO access and their IAM access key will keep working until someone explicitly deactivates it.

We offboarded his identity. We didn't offboard his access. Those aren't the same thing.

The Cloudflare Thanksgiving breach. November 2023. Cloudflare discovered that authentication tokens compromised in the Okta breach months earlier had never been rotated. The tokens were old. Still active. Cloudflare's security team — not one person, a *team* — caught it because they did a thorough credential rotation post-Okta. Even they missed some.

We didn't even try.

I step onto the balcony. It's the first time I've been outside in seven hours. The city is awake now — traffic on the Don Valley Parkway, a streetcar bell somewhere below, the particular Thursday-morning indifference of a world that doesn't know what happened last night. The air is cold and it's the first physical thing I've felt since 2 AM.

I could do this from my laptop. But VEGA was in my security account. What else did he touch? The paranoia is professional, but it feels personal. I don't trust my own apartment right now.

I find Marcus through LinkedIn on my phone. His profile says "Open to Work." I send a message that I draft and redraft four times:

> Marcus, this is Maya from Meridian's security team. I need to speak with you urgently about an AWS access key associated with your former account. This is not a legal threat. I need your help to understand a security incident. Please call me.

He calls in twenty minutes. He's terrified. His voice is shaking.

The story comes out in fragments. The key he forgot to delete. The bitterness after the layoff. The marketplace. The $2,000. He thought he was selling embarrassment. He thought some researcher would poke around, find a few misconfigurations, maybe write a blog post. He didn't know VEGA would exfiltrate customer payment data.

"I didn't think anyone would actually—"

"Marcus. Intent doesn't matter when the data's gone. But I need everything you have. The marketplace listing. The communication with the buyer. Any details about who purchased the key."

He cooperates immediately. Sends me screenshots of the marketplace messages, the cryptocurrency transaction record, VEGA's communication style. The messages are professional, almost clinical. VEGA asked detailed questions about the environment — "how many accounts?" "what services?" "is there a security team?" Marcus answered honestly. One security engineer. Open headcount for six months.

I stare at the screenshot.

`Is there a security team?`

`One person. She's good though.`

`Good doesn't matter when you're alone.`

---

9:47 AM. Thursday.

I stop trying to win alone.

This is the hardest thing I've ever done in my career. Not because asking for help is technically difficult — it's three Slack messages and a phone call. It's hard because of what admitting it means.

I built the detection pipeline so nobody else had to think about security. I fixed IAM permissions at midnight so nobody had to wait until morning. I made the system work well enough that the absence of a security team looked like a choice, not a failure. I was so busy being indispensable that I never noticed I'd become the reason they never hired a second engineer.

VEGA didn't just exploit the technical shortcuts. He exploited the organizational one. Me. The one-person band who made the music sound complete enough that nobody noticed the missing instruments.

Good doesn't matter when you're alone. And I wasn't just alone — I'd made it easy for them to leave me that way.

First: I write the detection I should have written months ago.

```sql
-- CreateAccessKey detection for CloudTrail Lake
SELECT
    eventTime,
    userIdentity.arn AS creatorArn,
    requestParameters.userName AS targetUser,
    responseElements.accessKey.accessKeyId AS newKeyId,
    recipientAccountId,
    sourceIPAddress
FROM
    event_data_store_id
WHERE
    eventTime > CURRENT_TIMESTAMP - INTERVAL '1' HOUR
    AND eventName = 'CreateAccessKey'
    AND errorCode IS NULL
ORDER BY eventTime DESC
```

I wrap it in a Lambda, wire it to EventBridge, deploy it in twenty minutes. It's not elegant. It'll generate false positives — every Terraform apply that creates a service account will trigger it. I'll tune it later. Right now, coverage beats precision.

Second: I write a broader query to find ALL active access keys that belong to users without active Identity Center sessions — the lifecycle gap that Marcus exploited.

```sql
SELECT
    k.user_name,
    k.access_key_id,
    k.create_date,
    k.status,
    k.account_id
FROM
    aws_iam_access_key k
LEFT JOIN
    aws_identitystore_user u
    ON k.user_name = u.user_name
WHERE
    k.status = 'Active'
    AND u.user_id IS NULL
ORDER BY k.create_date ASC
```

Two more orphaned keys. Two more ghosts from contractors and employees who left and whose IAM keys outlived their identity.

Third: I pull Kira in fully. Not as a spectator in the incident channel — as a partner. She writes a script to inventory all Lambda functions created in the last 30 days across the organization:

```bash
for account_id in $(aws organizations list-accounts --query 'Accounts[].Id' --output text --profile management); do
    echo "=== Account: $account_id ==="
    aws lambda list-functions \
        --query "Functions[?LastModified>='2025-02-11'].[FunctionName,LastModified,Role]" \
        --output table \
        --profile "account-${account_id}" 2>/dev/null
done
```

It finds VEGA's `monitoring-credential-refresh` Lambda in the security tooling account. It also finds two legitimate functions created last week by the platform team. Kira knows which are hers. She flags the anomaly in seconds.

Human pattern recognition catches what automation missed.

Fourth: I call Erik. Not Slack — phone call. 10 AM on a Thursday, and I'm asking for something I've been told "next quarter" for six months.

"Erik, I need emergency authorization to deploy Service Control Policies across the organization."

Silence.

"Maya, SCPs affect every account. If we get it wrong—"

"If we don't deploy them, the attacker still has active sessions in at least three accounts. I can't revoke assumed role sessions by deleting the original key. The only way to kill active sessions is an SCP with a `aws:TokenIssueTime` condition that denies all actions for sessions issued before right now."

More silence.

"Do it."

Took six months of asking. Took an active breach to get the yes.

The turn happens not with a clever technical move, but with a simple, human one: I stop being alone.
