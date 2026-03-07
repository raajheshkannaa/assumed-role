# Chapter 1: The Quiet Alert

---

2:14 AM. Thursday.

My phone buzzes on the nightstand. I know what it is before I look. The same way you know a car alarm at 3 AM isn't going to stop on its own — some sounds have a specific gravity that pulls you out of sleep and into dread.

Slack notification. `#security-alerts`. A channel with exactly one subscriber.

Me.

I should introduce myself. I'm Maya. I'm the security team at Meridian Financial. The entire security team. Me, my laptop, and a Slack channel nobody reads. I report to Erik, the VP of Engineering, who reports to the CTO, who reports to the CEO, who reports to the board, who reports to their golf buddies that they invested in a fintech startup with "robust security posture." That's me. I'm the robust security posture.

My mother calls every Sunday from Hyderabad. She asks if I'm eating properly. I tell her yes. She asks if I'm sleeping properly. I change the subject. She doesn't know what CloudTrail is. She knows her daughter works too hard.

Meridian processes payments. Series C, 400 employees, growing fast enough that the infrastructure team is perpetually underwater and the compliance team is two people who mostly fill out spreadsheets. We have 45 AWS accounts — which sounds like a lot until you realize that's the right number for a company handling credit card data across multiple product teams. Account-per-workload isolation. PCI-DSS demands it. AWS Well-Architected recommends it. And I'm the one person who has to watch all 45 of them.

I grab my phone.

```
#security-alerts
[CRITICAL] StopLogging detected in prod-payments-037
EventTime: 2025-03-13T06:11:43Z
Principal: arn:aws:iam::487291035561:user/svc-payment-processor
SourceIP: 98.47.216.103
```

My detection pipeline caught it. EventBridge rule monitoring CloudTrail management events, Lambda function that runs a CloudTrail Lake query, posts to Slack if the pattern matches. I built it six months ago on a Saturday because nobody asked me to and nobody would have noticed if I hadn't. That's the job. You build the thing, you maintain the thing, you respond to the thing, and if you do it well enough, nobody knows you exist.

`StopLogging`. Someone disabled CloudTrail in our production payments account. The account that processes credit card transactions.

I'm awake now.

---

Six hours earlier, I was fixing someone else's problem. That's not a complaint — it's just the shape of my days. Lena from the platform team had a deploy queued for Friday morning and her IAM role was missing `ssm:GetParameter` permissions. She'd pinged `#platform-help` at 4 PM, gotten one emoji reaction and no answers. By 8 PM, nobody had responded. I saw it at 11 PM, traced the issue to a permission boundary I'd applied last month to tighten service account scope, added the exception, tested it, sent Lena a DM: "Should be good now — the boundary was blocking SSM reads. I updated it."

She'll see it tomorrow. She won't know I stayed up until midnight for it. That's fine. I didn't do it for the credit.

I do a lot of things nobody notices. Last week I reviewed 47 Prowler findings — critical severity, the kind that make auditors sweat. I triaged 12. The other 35 are in a spreadsheet I'll get to next sprint. There's always a next sprint. One of those findings was about EC2 instances running IMDSv1 — the instance metadata service version that lets anyone on the network grab IAM credentials with a simple HTTP request. I flagged it, marked it "acknowledged — will remediate next quarter," and moved on.

We have GuardDuty enabled across all accounts. That was Erik's checkbox. "We have GuardDuty." We also have 2,300 unreviewed findings. Enabling a service isn't the same as using it. GuardDuty is a smoke detector in a building where nobody checks if the batteries work.

But the detection pipeline — that's mine. CloudTrail events flow into CloudTrail Lake, I write SQL queries against the event data store, and EventBridge triggers Lambda functions when specific patterns appear. It's not sophisticated. It's just *consistent*. I wrote detections for the things that scare me most: `StopLogging`, `DeleteTrail`, `PutBucketPolicy` with public access, `ConsoleLogin` without MFA. The basics. The things that, if you miss them, you're already three moves behind.

Tonight, the basics just paid off.

---

I pull my laptop from the nightstand — it never goes far — and open a terminal.

```bash
granted sso login --profile security-tooling
```

Granted handles my credential management. Ironic, really — I use a secure credential broker for my own access, but half our service accounts have access keys that haven't been rotated since the Obama administration. Do as I say, not as my company does.

First thing: verify the alert is real and not a misconfigured automation. I've been burned before. Two months ago, an intern's CloudFormation stack tried to create a trail in a sandbox account and the `CreateTrail` event triggered my alert. I spent 40 minutes investigating a false positive. At 2 AM, I need to know what I'm dealing with before I burn adrenaline.

I open CloudTrail Lake and run the query:

```sql
SELECT
    eventTime,
    eventName,
    eventSource,
    sourceIPAddress,
    userIdentity.arn AS principalArn,
    userIdentity.accessKeyId,
    requestParameters,
    responseElements,
    errorCode
FROM
    event_data_store_id
WHERE
    eventTime > '2025-03-13T05:00:00Z'
    AND recipientAccountId = '487291035561'
    AND userIdentity.accessKeyId = 'AKIAIOSFODNN7EXAMPLE'
ORDER BY eventTime ASC
```

The results come back. I read CloudTrail events the way some people read sheet music — each line tells a story if you know how to listen.

```json
{
    "eventVersion": "1.09",
    "userIdentity": {
        "type": "IAMUser",
        "principalId": "AIDACKCEVSQ6C2EXAMPLE",
        "arn": "arn:aws:iam::487291035561:user/svc-payment-processor",
        "accountId": "487291035561",
        "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
        "userName": "svc-payment-processor"
    },
    "eventTime": "2025-03-13T05:47:12Z",
    "eventSource": "ec2.amazonaws.com",
    "eventName": "DescribeInstances",
    "awsRegion": "us-east-1",
    "sourceIPAddress": "98.47.216.103",
    "userAgent": "aws-cli/2.15.17 md/Botocore#1.34.17 ua/2.0 os/linux#5.15.0-91-generic"
}
```

Same principal, same source IP. Three more events in rapid succession: `DescribeSecurityGroups` at 05:48, `GetCallerIdentity` at 05:49, then a twenty-two minute pause — and `StopLogging` at 06:11:

```json
{
    "eventTime": "2025-03-13T06:11:43Z",
    "eventSource": "cloudtrail.amazonaws.com",
    "eventName": "StopLogging",
    "sourceIPAddress": "98.47.216.103",
    "requestParameters": {
        "name": "arn:aws:cloudtrail:us-east-1:487291035561:trail/meridian-org-trail"
    },
    "responseElements": null
}
```

`DescribeInstances` → `DescribeSecurityGroups` → `GetCallerIdentity` → `StopLogging`.

That's not an automation misconfiguration. That's a recon pattern. Someone logged in, looked around, figured out who they were, and then turned off the cameras.

The source IP — `98.47.216.103` — is a residential ISP address. Not our corporate VPN. Not a known AWS IP range. Someone's sitting in an apartment somewhere, using credentials that belong to a service account in our most sensitive production account.

I keep thinking about that healthcare company that went down last year. Single credential. No MFA. Twenty-two billion dollar parent company, months to recover. One set of credentials on a portal nobody was watching. We're not a twenty-two billion dollar company. We're one security engineer talking to herself at 2 AM.

CloudTrail doesn't lie. People lie. CloudTrail just writes it down.

---

I check the access key metadata:

```bash
aws iam list-access-keys --user-name svc-payment-processor \
    --profile prod-payments --output json
```

```json
{
    "AccessKeyMetadata": [
        {
            "UserName": "svc-payment-processor",
            "AccessKeyId": "AKIAIOSFODNN7EXAMPLE",
            "Status": "Active",
            "CreateDate": "2024-09-15T14:22:07Z"
        }
    ]
}
```

Created September 15, 2024. Six months ago. Never rotated. `Status: Active`.

I already know this is bad. You're reading this thinking "just revoke the key." Yeah. I thought that too. Hold that thought.

There's something else in the timeline that bothers me. The gap between `GetCallerIdentity` at 05:49 and `StopLogging` at 06:11 — twenty-two minutes. That's not a script running sequentially. Someone stopped. Read the output of `GetCallerIdentity`. Understood what the service account could do. Made a decision. Then disabled logging.

That's a human. A patient one.

I look at my phone. 2:38 AM. The `#security-alerts` channel sits there, one unread notification, zero other subscribers.

Either this is something I can explain away by morning, or someone just went dark in our most sensitive account and I'm the only person who knows.

I really hope it's the first one.

I open a new terminal tab.

```bash
granted sso login --profile prod-payments
```

Time to find out.
