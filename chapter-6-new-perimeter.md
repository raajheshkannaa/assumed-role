# Chapter 6: New Perimeter

---

2:12 PM. Thursday. Bucharest.

VEGA opened a terminal and ran a count on the objects landing in his destination bucket. 847,000 transaction records and climbing. The replication was still running — AWS copying files silently, dutifully, the way it was designed to.

He should have felt triumphant. This was clean work. No malware, no zero-days, no traces that couldn't be explained as normal operations. Just AWS doing what AWS does, pointed in a direction nobody was watching.

Instead, he opened a browser tab and navigated to Meridian's About page. Team photos from an offsite. A blog post about their charity hackathon. A headshot of someone named Lena holding a trophy. He closed the tab.

The radiator ticked. The dog downstairs was quiet this morning.

He started drafting the assessment — the five-point list he'd leave for Marcus to relay. Not because anyone asked. Because without framing this as a service, he'd have to sit with what it actually was: 847,000 records belonging to people who had never heard of him, copied to a server in a country they'd never visit, by a man who told himself this was education.

He wrote the first line: *"You're looking for damage. Let me save you some time."*

The radiator ticked.

---

10:34 AM. Thursday.

Containment. Systematic. Step by step.

Steps one and two: delete the backdoor and kill its self-healing mechanism.

```bash
# Delete the access keys for the backdoor user
aws iam list-access-keys --user-name svc-monitoring-agent \
    --profile security-tooling --output json | \
    jq -r '.AccessKeyMetadata[].AccessKeyId' | \
    while read key_id; do
        aws iam delete-access-key \
            --user-name svc-monitoring-agent \
            --access-key-id "$key_id" \
            --profile security-tooling
        echo "Deleted key: $key_id"
    done

# Detach the policy
aws iam detach-user-policy \
    --user-name svc-monitoring-agent \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess \
    --profile security-tooling

# Delete the user
aws iam delete-user \
    --user-name svc-monitoring-agent \
    --profile security-tooling

# Kill the self-healing mechanism — remove EventBridge trigger and Lambda
aws events remove-targets \
    --rule monitoring-refresh-schedule \
    --ids "monitoring-credential-refresh-target" \
    --profile security-tooling

# Delete the EventBridge rule
aws events delete-rule \
    --name monitoring-refresh-schedule \
    --profile security-tooling

# Delete the Lambda function
aws lambda delete-function \
    --function-name monitoring-credential-refresh \
    --profile security-tooling
```

Step three: the nuclear option.

This is the SCP. The one I've been asking to deploy for six months. The one that was always "next quarter." It denies all actions for any session token issued before a specific timestamp — effectively revoking every active session in the targeted accounts.

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RevokeActiveSessions",
            "Effect": "Deny",
            "Action": "*",
            "Resource": "*",
            "Condition": {
                "DateLessThan": {
                    "aws:TokenIssueTime": "2025-03-13T14:30:00Z"
                }
            }
        }
    ]
}
```

I deploy it to the compromised accounts — `prod-payments-037`, `dev-platform-012`, `staging-data-019`, `prod-datalake-031`, and the security tooling account.

```bash
aws organizations create-policy \
    --name "EmergencySessionRevocation" \
    --description "Revoke all sessions issued before 2025-03-13T14:30:00Z" \
    --type SERVICE_CONTROL_POLICY \
    --content file://revoke-sessions-scp.json \
    --profile management

# Attach to compromised accounts
for account_id in 487291035561 293847561029 384756102938 561029384756 192837465019; do
    aws organizations attach-policy \
        --policy-id p-examplerevoke \
        --target-id "$account_id" \
        --profile management
    echo "SCP attached to $account_id"
done
```

And then I make my third mistake.

---

10:51 AM. Thursday.

```
#incident-20250313
Kira: Maya — the payments deploy pipeline just failed. All CI/CD
actions are being denied. The SCP is blocking the pipeline's
assumed role sessions.
```

The SCP is too broad. It doesn't just revoke VEGA's sessions — it revokes *all* sessions issued before 14:30. Including the CI/CD pipeline's. Including the data processing jobs. Including the monitoring Lambdas. Including everything.

I deployed a session-killing SCP to five accounts without scoping it to only the compromised principals. At 4 AM, running on adrenaline and four hours of sleep, I wrote a policy that says "deny everything for everyone" when I meant to say "deny everything for the attacker."

Kira catches it in ten minutes. Ten minutes during which the payments pipeline is down and the payment processing queue is backing up.

```
Kira: I can scope it. Give me 5 min. We can add a condition that
excludes our CI/CD role ARNs and known service roles.
```

She rewrites the SCP:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RevokeCompromisedSessions",
            "Effect": "Deny",
            "Action": "*",
            "Resource": "*",
            "Condition": {
                "DateLessThan": {
                    "aws:TokenIssueTime": "2025-03-13T14:30:00Z"
                },
                "ArnNotLike": {
                    "aws:PrincipalArn": [
                        "arn:aws:iam::*:role/cicd-*",
                        "arn:aws:sts::*:assumed-role/cicd-*/*",
                        "arn:aws:iam::*:role/meridian-service-*",
                        "arn:aws:sts::*:assumed-role/meridian-service-*/*",
                        "arn:aws:iam::*:role/AWSServiceRole*",
                        "arn:aws:sts::*:assumed-role/AWSServiceRole*/*"
                    ]
                }
            }
        }
    ]
}
```

I update the policy. The CI/CD pipeline recovers. The payment queue drains.

Kira just saved me from causing a self-inflicted outage worse than the breach. This is why you don't do incident response alone at 4 AM. This is why you ask for help.

Step four: cut the exfiltration.

```bash
# Remove the S3 replication rule to VEGA's external account
aws s3api put-bucket-replication \
    --bucket meridian-datalake-raw \
    --replication-configuration '{
        "Role": "arn:aws:iam::561029384756:role/s3-replication-role",
        "Rules": [{
            "ID": "datalake-replica",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Destination": {
                "Bucket": "arn:aws:s3:::meridian-datalake-replica",
                "Account": "561029384756",
                "StorageClass": "STANDARD"
            }
        }]
    }' \
    --profile prod-datalake
```

Step five: close the doors VEGA walked through.

```bash
# Enforce IMDSv2 on all instances in dev-platform
for instance_id in i-0a1b2c3d4e5f6g7 i-0h8i9j0k1l2m3n4 i-0v2w3x4y5z6a7b8; do
    aws ec2 modify-instance-metadata-options \
        --instance-id "$instance_id" \
        --http-tokens required \
        --http-endpoint enabled \
        --profile dev-platform
    echo "IMDSv2 enforced on $instance_id"
done
```

The Prowler finding I ignored for three months. Remediated in thirty seconds. Three months of deferrals resolved with one CLI command per instance.

Step six: rotate every service account key in the compromised accounts.

```bash
aws iam generate-credential-report --profile prod-payments
aws iam get-credential-report --profile prod-payments --output json | \
    jq -r '.Content' | base64 -d > /tmp/cred-report.csv

# Column 1: user, Column 9: access_key_1_active, Column 10: access_key_1_last_rotated
head -1 /tmp/cred-report.csv | tr ',' '\n' | nl  # verify column positions
grep -E "svc-|service-" /tmp/cred-report.csv | \
    awk -F',' '{print $1, $9, $10}'
```

```
svc-payment-processor  true  N/A
svc-data-pipeline      true  N/A
svc-notification       true  N/A
```

`N/A` across the board. None of them have ever been rotated. I cross-reference creation dates from `list-access-keys` — the oldest is `svc-data-pipeline`, key created April 2023. Almost a year old. Another time bomb.

I rotate all three. Create new keys, update the services that consume them, deactivate the old ones. Kira handles the payment service configuration. We work in parallel. It takes an hour.

Step seven: preserve the evidence.

```bash
# Copy all CloudTrail logs for the incident timeframe to a forensic account
aws s3 sync \
    s3://meridian-cloudtrail-logs/AWSLogs/ \
    s3://meridian-forensic-evidence/incident-20250313/cloudtrail/ \
    --include "*2025-03-0*" --include "*2025-03-1*" \
    --profile forensic-account

# Copy VPC Flow Logs
aws s3 sync \
    s3://meridian-vpc-flow-logs/ \
    s3://meridian-forensic-evidence/incident-20250313/vpc-flow-logs/ \
    --include "*2025-03-1*" \
    --profile forensic-account

# Copy S3 server access logs
aws s3 sync \
    s3://meridian-s3-access-logs/ \
    s3://meridian-forensic-evidence/incident-20250313/s3-access-logs/ \
    --include "*2025-03-1*" \
    --profile forensic-account
```

Chain of custody. Separate account. Read-only access. If this goes to law enforcement — and it might — the evidence needs to be untouched.

---

2:17 PM. Thursday.

Marcus sends me one more thing. A final message from VEGA, posted to the marketplace dead drop after Marcus asked him what he'd done with the credentials.

It's not a threat. It's a *professional assessment*.

```
You're looking for damage. Let me save you some time. Here are five
things your security engineer already knows but hasn't fixed. I'm
including CloudTrail event IDs so she can verify each one.

1. Service account keys with no rotation policy
   (svc-payment-processor: last rotated never. Created 2024-09-15.
   EventId: a1b2c3d4-e5f6-7890-abcd-ef1234567890)

2. IMDSv1 on production EC2 instances
   (3 instances in dev-platform-012. HttpTokens: optional.
   You know the CVE. Everyone knows the CVE.)

3. Cross-account role trust: any spoke can assume into any other spoke.
   Blast radius = infinite.
   (EventId for my first lateral move:
   b2c3d4e5-f6a7-8901-bcde-f12345678901)

4. No detection for IAM credential creation events.
   I created a user with AdministratorAccess in the security account.
   Nobody noticed for 3 days.
   (EventId: c3d4e5f6-a7b8-9012-cdef-123456789012)

5. S3 replication: no monitoring, no alerting, no restrictions on
   destination accounts.
   I replicated your transaction data to my account using your own
   replication role.
   (EventId: d4e5f6a7-b8c9-0123-defa-234567890123)

Your engineer is talented. She built a real detection system with no
budget, no team, and no support. The queries are elegant. The
architecture is sound. But one person cannot defend forty-five accounts.
That isn't a criticism — it's a structural fact.

You're welcome.

— V
```

I read it three times.

Four of the five are things I already knew. Things I had in my backlog. Things in a spreadsheet I promised myself I'd get to.

He's not wrong. That's the worst part. He's not wrong about any of it. He's just wrong about what it justifies.

VEGA believes he's the audit Meridian refused to pay for. The penetration test that exposes the truth. The bitter medicine. And some of his logic tracks — companies *do* under-invest in security. One person *can't* watch 45 accounts. Compliance checkboxes *aren't* the same as security.

But the data he exfiltrated belongs to humans. Not to Meridian, not to the board, not to the executives who decided one security engineer was enough. To the customers. The people whose transaction records are now in an account controlled by someone who bought stolen credentials on a dark web marketplace. Those people didn't under-invest in security. They just trusted the wrong company with their data.

You don't get to decide the cost of proving a point with other people's lives.

---

4:00 PM. Thursday.

I present to Erik, the CTO, and the head of legal. Not with fear — with a plan and a timeline.

The head of legal — Sara — speaks first. "How much customer data was exposed?"

"Fourteen months of transaction records. Customer names, payment amounts, partial card numbers, billing addresses. PCI tokenization protected the full card data, but what was exposed is enough to trigger state breach notification laws in every jurisdiction where we have customers."

The room goes quiet. Sara writes something on her pad without looking up. "We need to notify affected customers within 72 hours under CCPA. 60 days under most state laws. We need outside counsel."

She flips the pad around so I can see it. A column of numbers in neat handwriting. "Preliminary estimate: breach notification, outside counsel, credit monitoring for affected customers, regulatory fines, customer churn. Conservative range is three to five million." She pauses. "That's fifteen times what a second security hire would have cost over the same period."

Nobody says anything. The math is simple enough that it doesn't need to be.

The CTO — who has been silent — asks the question executives always ask: "Can we contain this quietly?"

"No." I don't soften it. "The data left our environment via S3 replication to an external account. We don't control that account. We have no way to confirm deletion. This is a reportable breach. If we try to bury it and it comes out later — and it will — the regulatory response will be worse than the breach."

Sara nods. The CTO looks at Erik. Erik looks at me.

"We passed our SOC 2 audit three months ago," I tell them. "During that audit, the attacker was already inside our environment. VEGA created the backdoor IAM user on March 10th. Our SOC 2 Type II observation period ended February 28th. Compliance isn't security. It never was."

I lay out the remediation plan:

**Immediate (this week):**
- Temporary access only — just-in-time access provisioned through Identity Center with automatic expiration. No permanent admin keys for human users. No exceptions.
- Access key lifecycle automation — when an Identity Center session is deprovisioned, all associated programmatic keys are deactivated automatically. The lifecycle gap that Marcus exploited dies.
- IMDSv2 enforcement — organization-wide SCP. Not per-instance metadata options that can be overridden. An SCP that denies `ec2:RunInstances` and `ec2:ModifyInstanceMetadataOptions` unless `HttpTokens` is `required`. No exceptions.

**This month:**
- S3 replication monitoring — CloudTrail Lake detection for any `PutBucketReplication` event where the destination account is not in our organization. Alerting within minutes, not hours.
- Cross-account role trust tightening — spoke roles can only assume into accounts within their own business unit. Payment accounts don't need access to dev accounts. The blast radius shrinks from 45 accounts to 4.
- Quarterly Prowler scans with SLA for critical findings. "Acknowledged" is not "remediated." Every critical finding gets a remediation date, and I track them like SLA breaches.

**This quarter:**
- A second security hire. Non-negotiable. I've been saying this for a year. Today is the evidence.

Erik is quiet for a long time. Then:

"Draft the job listing tonight. I'll post it tomorrow."

The next 72 hours blur. Sara's legal team drafts breach notification letters for affected customers — state-by-state, because every jurisdiction has different requirements. The board holds an emergency session on Friday evening. I present the technical timeline while executives ask variations of the same question: "How did this happen?" The answer is always the same: one credential, one person, one set of shortcuts that were "good enough" until they weren't.

Customer notification goes out Monday morning. 2.3 million affected accounts. The inbox floods. PR handles the external messaging. I handle the technical questions from customers' security teams who want to know exactly what was exposed. I answer every one honestly. It's the least we owe them.

---

11:47 PM. Thursday.

Twenty-one hours since the first alert. The attacker's access is revoked. The backdoor is deleted. The self-healing Lambda is gone. The S3 replication is restored to internal-only. IMDSv2 is enforced. Service account keys are rotated. Evidence is preserved.

I should sleep. I'm going to sleep. But first.

I open the Identity Center automation codebase — the GitOps pipeline that manages permission sets and access assignments. The one that currently provisions permanent access because it was easier to build that way. Because I was one person and "make it work" was the priority.

I write a new module. Temporary access controls. When you request access to a production account, you get it for 4 hours. Then it expires. If you need it again, you request it again. An audit trail for every session. No more permanent anything.

It takes me an hour. I test it against the staging Identity Center instance. It works. I push the PR.

```
feat: temporary access controls for Identity Center

JIT (just-in-time) access provisioning with automatic expiration.
No more permanent admin. No more keys that outlive the people
who created them. No more next quarter.

If you're reading this and you have service account keys older
than 90 days, rotate them. Right now. Not next quarter.
```

---

One week later. 2:04 AM. Thursday.

My phone buzzes. Slack notification from `#security-alerts`.

But this time, there are three subscribers.

Kira joined the channel the day after the incident. Didn't ask permission. Just appeared. She set up a personal notification schedule — alerts during her working hours route to her, off-hours to me. We overlap for two hours in the middle.

And there's a third subscriber now. Kai — Meridian's second security engineer. Starts Monday. I interviewed them last Friday. They asked about our detection coverage during the interview, and I was honest: "We have gaps. I'll show you exactly where they are on your first day." They smiled and said, "That's the first honest answer I've gotten in twelve interviews."

I check the alert. My new detection — `CreateAccessKey` — firing on the sandbox account.

```
#security-alerts
[HIGH] CreateAccessKey detected in sandbox-platform-041
EventTime: 2025-03-20T06:02:17Z
Principal: arn:aws:iam::738495061728:user/dev-sandbox-user
SourceIP: 10.0.47.128 (internal VPN)
NewKeyId: AKIAEXAMPLESANDBOX01
```

I trace it. A developer testing a Lambda function in the sandbox. They created an access key to run `aws s3 cp` from their local machine. Standard development workflow.

False positive. I mark it resolved and add a filter for sandbox accounts to reduce noise. The detection stays on — it just gets smarter.

I close my laptop. The apartment is dark. My phone is on the nightstand. The `#security-alerts` channel has three subscribers and a new detection that catches the thing that almost killed us.

I go back to sleep.
