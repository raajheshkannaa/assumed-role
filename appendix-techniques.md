# Appendix: Technical Reference

Every technique in "Assumed Role" maps to real AWS behavior, real MITRE ATT&CK techniques, and real incidents. This appendix serves as a reference for defenders who want to build the detections Maya built — and the ones she didn't.

---

## Attack Techniques Used by VEGA

### 1. Initial Access: Stolen Credentials from Contractor

**MITRE ATT&CK**: [T1078.004 — Valid Accounts: Cloud Accounts](https://attack.mitre.org/techniques/T1078/004/)

**What happened**: Marcus exported an IAM access key to his personal machine during his contract. When his contract ended, his Identity Center SSO was deprovisioned, but the IAM access key persisted. He sold the key on a dark web marketplace.

**Real-world parallels**:
- **Cloudflare Thanksgiving 2023**: Authentication tokens from the Okta breach were never rotated. Months-old tokens remained active.
- **Uber 2022**: Contractor targeted via MFA fatigue attack (Lapsus$/Scattered Spider). Attacker spammed push notifications until the contractor approved. Lateral movement followed.
- **Change Healthcare 2024**: Single stolen credential without MFA on a Citrix portal. $22B parent company compromised.

**Detection (CloudTrail Lake)**:
```sql
-- Find active access keys for users without Identity Center sessions
SELECT
    eventTime,
    userIdentity.accessKeyId,
    userIdentity.userName,
    sourceIPAddress,
    eventName
FROM event_data_store_id
WHERE
    userIdentity.type = 'IAMUser'
    AND sourceIPAddress NOT IN (/* known corporate IP ranges */)
    AND eventTime > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
ORDER BY eventTime DESC
```

**Prevention**: Automated access key lifecycle management. When Identity Center sessions are deprovisioned, all associated IAM access keys should be deactivated automatically.

---

### 2. Discovery: Automated Enumeration

**MITRE ATT&CK**: [T1087.004 — Account Discovery: Cloud Account](https://attack.mitre.org/techniques/T1087/004/)

**What happened**: VEGA used Pacu's `iam__enum_permissions` module to map the service account's permissions, then manually enumerated EC2, S3, and IAM resources.

**API calls (in order)**: `GetCallerIdentity`, `GetUser`, `ListAttachedUserPolicies`, `ListUserPolicies`, `GetPolicyVersion`, `DescribeInstances`, `DescribeSecurityGroups`, `ListBuckets`, `ListRoles`

**Tools**: [Pacu](https://github.com/RhinoSecurityLabs/pacu) — AWS exploitation framework

**Detection (CloudTrail Lake)**:
```sql
-- Detect enumeration patterns: multiple Describe/List calls in short timeframe
SELECT
    userIdentity.arn,
    sourceIPAddress,
    COUNT(DISTINCT eventName) AS distinct_api_calls,
    MIN(eventTime) AS first_call,
    MAX(eventTime) AS last_call
FROM event_data_store_id
WHERE
    eventTime > CURRENT_TIMESTAMP - INTERVAL '1' HOUR
    AND (eventName LIKE 'Describe%' OR eventName LIKE 'List%' OR eventName LIKE 'Get%')
GROUP BY userIdentity.arn, sourceIPAddress
HAVING COUNT(DISTINCT eventName) > 15
```

---

### 3. Defense Evasion: CloudTrail StopLogging

**MITRE ATT&CK**: [T1562.008 — Impair Defenses: Disable or Modify Cloud Logs](https://attack.mitre.org/techniques/T1562/008/)

**What happened**: VEGA disabled CloudTrail in the production payments account, creating a 22-minute blind spot.

**CloudTrail event**: `cloudtrail:StopLogging`

**Detection (EventBridge rule)**:
```json
{
    "source": ["aws.cloudtrail"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
        "eventName": ["StopLogging", "DeleteTrail", "UpdateTrail"],
        "eventSource": ["cloudtrail.amazonaws.com"]
    }
}
```

**Alternative evidence when CloudTrail is disabled**:
- VPC Flow Logs (network-level, independent of CloudTrail)
- S3 Server Access Logs (object-level access, separate logging pipeline)
- RDS Query Logs (database-level, stored in CloudWatch Logs)

---

### 4. Lateral Movement: Cross-Account Role Assumption

**MITRE ATT&CK**: [T1550.001 — Use Alternate Authentication Material: Application Access Token](https://attack.mitre.org/techniques/T1550/001/)

**What happened**: VEGA used overly permissive cross-account role trust policies to assume `spoke-001` roles across multiple accounts. The hub-spoke architecture had a "trust all spokes" design that allowed any account to assume into any other.

**CloudTrail event**: `sts:AssumeRole`

**Detection (CloudTrail Lake)**:
```sql
-- Cross-account role assumptions from unexpected source accounts
SELECT
    eventTime,
    userIdentity.accountId AS sourceAccount,
    recipientAccountId AS targetAccount,
    requestParameters.roleArn AS assumedRole,
    sourceIPAddress
FROM event_data_store_id
WHERE
    eventName = 'AssumeRole'
    AND userIdentity.accountId != recipientAccountId
    AND eventTime > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
ORDER BY eventTime DESC
```

**Prevention**: Least-privilege role trust policies. Spoke roles should only trust specific accounts within the same business unit, not the entire organization.

---

### 5. Credential Access: SSRF to IMDSv1

**MITRE ATT&CK**: [T1552.005 — Unsecured Credentials: Cloud Instance Metadata API](https://attack.mitre.org/techniques/T1552/005/)

**What happened**: VEGA used SSM Session Manager (via the assumed role's `ssm:StartSession` permissions) to access an EC2 instance in the dev account, then exploited an SSRF vulnerability in an internal dev tool running on the instance to grab instance role credentials from the metadata service at `169.254.169.254`. The instances had `HttpTokens: optional` (IMDSv1), meaning no session token was required.

**Real-world parallel**: **Capital One 2019** — Former AWS engineer exploited SSRF → IMDSv1 to exfiltrate 100M+ customer records. The core issue: IMDSv1 doesn't require a session token, so any SSRF can access it.

**Detection**:
```bash
# Prowler check for IMDSv2 enforcement
prowler aws --check ec2_instance_imdsv2_enabled
```

**Prevention (SCP to enforce IMDSv2 org-wide)**:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "RequireIMDSv2",
            "Effect": "Deny",
            "Action": "ec2:RunInstances",
            "Resource": "arn:aws:ec2:*:*:instance/*",
            "Condition": {
                "StringNotEquals": {
                    "ec2:MetadataHttpTokens": "required"
                }
            }
        },
        {
            "Sid": "PreventIMDSv2Downgrade",
            "Effect": "Deny",
            "Action": "ec2:ModifyInstanceMetadataOptions",
            "Resource": "arn:aws:ec2:*:*:instance/*",
            "Condition": {
                "StringNotEquals": {
                    "ec2:MetadataHttpTokens": "required"
                }
            }
        }
    ]
}
```

---

### 6. Persistence: Backdoor IAM User + Self-Healing Lambda

**MITRE ATT&CK**: [T1136.003 — Create Account: Cloud Account](https://attack.mitre.org/techniques/T1136/003/) + [T1053.007 — Scheduled Task/Job: Serverless Execution](https://attack.mitre.org/techniques/T1053/007/)

**What happened**: VEGA created an IAM user `svc-monitoring-agent` with `AdministratorAccess` in the security tooling account, then deployed a Lambda function triggered by EventBridge every 6 hours to refresh credentials — ensuring the backdoor survived key deletion.

**CloudTrail events**: `iam:CreateUser`, `iam:AttachUserPolicy`, `iam:CreateAccessKey`, `lambda:CreateFunction20150331`, `events:PutRule`

**Detection (CloudTrail Lake)**:
```sql
-- Detect IAM user creation with admin policies
SELECT
    eventTime,
    userIdentity.arn AS creator,
    requestParameters.userName AS newUser,
    recipientAccountId,
    sourceIPAddress
FROM event_data_store_id
WHERE
    eventName = 'CreateAccessKey'
    AND errorCode IS NULL
    AND eventTime > CURRENT_TIMESTAMP - INTERVAL '24' HOUR
ORDER BY eventTime DESC
```

---

### 7. Exfiltration: S3 Cross-Account Replication

**MITRE ATT&CK**: [T1537 — Transfer Data to Cloud Account](https://attack.mitre.org/techniques/T1537/)

**What happened**: VEGA configured S3 replication from `meridian-datalake-raw` to an external account he controlled. S3 replication is asynchronous — AWS copies objects in the background. No additional API calls appear in the source account's CloudTrail for the actual data transfer. The destination bucket must have a bucket policy granting the source account's replication role `s3:ReplicateObject` and `s3:ReplicateDelete` permissions, and the source bucket must have versioning enabled.

**CloudTrail event**: `s3:PutBucketReplication`

**Detection (CloudTrail Lake)**:
```sql
-- Detect S3 replication to accounts outside the organization
SELECT
    eventTime,
    recipientAccountId,
    requestParameters.bucketName,
    requestParameters.ReplicationConfiguration,
    sourceIPAddress
FROM event_data_store_id
WHERE
    eventName = 'PutBucketReplication'
    AND eventTime > CURRENT_TIMESTAMP - INTERVAL '30' DAY
ORDER BY eventTime DESC
```

**Prevention**: SCP denying `s3:PutBucketReplication` unless the destination account is within the organization.

---

### 8. Diversion: Security Group Modification as Decoy

**MITRE ATT&CK**: [T1562.007 — Impair Defenses: Disable or Modify Cloud Firewall](https://attack.mitre.org/techniques/T1562/007/)

**What happened**: VEGA modified a security group to allow `0.0.0.0/0` on port 5432 as a deliberate distraction, drawing Maya's attention to the database while the real exfiltration happened via S3 replication.

**CloudTrail event**: `ec2:AuthorizeSecurityGroupIngress`

**Detection & auto-remediation**:
```json
{
    "source": ["aws.ec2"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
        "eventName": ["AuthorizeSecurityGroupIngress"],
        "requestParameters": {
            "ipPermissions": {
                "items": {
                    "ipRanges": {
                        "items": {
                            "cidrIp": ["0.0.0.0/0"]
                        }
                    }
                }
            }
        }
    }
}
```

**Note**: EventBridge content-based filtering has limited support for deep nested array matching. In practice, this pattern may not match reliably. A more robust approach is to use a Lambda function triggered by all `AuthorizeSecurityGroupIngress` events, then inspect `requestParameters` in the Lambda code to check for `0.0.0.0/0`.

---

### 9. Session Persistence: STS Token Survival

**MITRE ATT&CK**: [T1550.001 — Use Alternate Authentication Material](https://attack.mitre.org/techniques/T1550/001/)

**What happened**: After Maya revoked the original access key, VEGA's assumed role sessions (STS temporary credentials) remained valid. STS session tokens are independent of the calling credential — revoking the caller's key does not invalidate sessions it already created.

**AWS behavior**: Assumed role sessions can last up to 12 hours (default: 1 hour, configurable). Revoking the source credential does NOT revoke the session.

**Remediation (SCP with TokenIssueTime)**:
```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Deny",
        "Action": "*",
        "Resource": "*",
        "Condition": {
            "DateLessThan": {
                "aws:TokenIssueTime": "2025-03-13T14:30:00Z"
            },
            "StringNotLike": {
                "aws:PrincipalArn": [
                    "arn:aws:iam::*:role/cicd-*",
                    "arn:aws:iam::*:role/AWSServiceRole*"
                ]
            }
        }
    }]
}
```

**Important limitation**: `aws:TokenIssueTime` only applies to temporary credentials (STS assumed role sessions, federated sessions). It does NOT apply to long-term IAM user access keys. To revoke IAM user access, deactivate or delete the access key directly.

---

## Maya's Toolkit

| Tool | Category | How Used |
|------|----------|----------|
| **CloudTrail Lake** | AWS Native | Primary detection engine — SQL queries against CloudTrail event data store |
| **EventBridge** | AWS Native | Real-time pattern matching on CloudTrail events, triggering Lambda for alerting |
| **GuardDuty** | AWS Native | Enabled (2,300 unreviewed findings). Secondary signal, not primary detection |
| **AWS Config** | AWS Native | Continuous compliance checks. Gap: periodic evaluation cycle allows changes within the window |
| **IAM Access Analyzer** | AWS Native | External access detection. Found the overly permissive spoke role trust |
| **SCPs** | AWS Native | Nuclear option for session revocation. Also used for IMDSv2 enforcement |
| **VPC Flow Logs** | AWS Native | Network-level evidence when CloudTrail was disabled |
| **S3 Server Access Logs** | AWS Native | Object-level access evidence independent of CloudTrail |
| **Prowler** | Open Source | Security posture assessment. Flagged IMDSv1 instances 3 months before the breach |
| **Steampipe** | Open Source | SQL interface to AWS APIs. Ad-hoc investigation faster than writing boto3 |
| **Granted** | Open Source | Secure credential management for Maya's own access |
| **truffleHog** | Open Source | Secret scanning in git repositories. Found 2 more leaked keys post-incident |
| **Pacu** | Open Source | Referenced as VEGA's tool. AWS exploitation framework for privilege escalation enumeration |

---

## Real Incidents Referenced

| Incident | Year | Relevance to Story |
|----------|------|--------------------|
| **Capital One** | 2019 | SSRF → IMDSv1 → S3 exfil. Same vulnerability class VEGA exploited |
| **Uber** | 2022 | Contractor targeted via MFA fatigue (Lapsus$). Social engineering + lateral movement |
| **Cloudflare Thanksgiving** | 2023 | Un-rotated Okta tokens. Mirrors Marcus's un-revoked access key |
| **Change Healthcare** | 2024 | Single credential, no MFA. Maya cites this to Rohan |
| **MGM/Caesars** | 2023 | Social engineering help desk for MFA reset. Identity provider abuse |
| **Microsoft Midnight Blizzard** | 2024 | OAuth app abuse in legacy test tenant. Parallels VEGA finding gaps in less-monitored accounts |
| **CircleCI** | 2023 | Stolen engineer credential → customer secret exposure |
| **SolarWinds** | 2020 | Supply chain trust. VEGA's access came through a trusted service account role |

---

## Defensive Gaps Exploited (& How to Fix Them)

| Gap | Chapter | Fix |
|-----|---------|-----|
| Access key not revoked on contractor offboarding | 2 | Automate key lifecycle with Identity Center deprovisioning |
| IMDSv1 on EC2 instances | 3 | Org-wide SCP enforcing `ec2:MetadataHttpTokens: required` |
| Cross-account role trust too permissive | 3 | Scope trust policies to business-unit accounts only |
| No detection for `CreateAccessKey` | 5 | CloudTrail Lake query + EventBridge → Lambda → Slack |
| No monitoring for S3 replication changes | 4 | Detect `PutBucketReplication` to external accounts |
| STS sessions survive key revocation | 4 | SCP with `aws:TokenIssueTime` condition |
| AWS Config evaluation delay | 4 | Supplement with real-time EventBridge detections |
| GuardDuty findings unreviewed (2,300+) | 1 | Prioritize + automate triage. Alert fatigue kills detection |
| Prowler findings marked "acknowledged" | 5 | SLA-based remediation tracking. Acknowledged != fixed |
| S3 data events not enabled (cost) | 3 | Enable at least for sensitive buckets. The cost of not having them is higher |
