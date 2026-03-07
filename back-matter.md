# Back Matter

## Author's Note

Every attack in this book happened somewhere. The credential that was never revoked. The IMDSv1 instance nobody patched. The security group opened for five seconds. The S3 replication rule nobody monitored. Different companies, different years, same patterns.

Maya is fictional. Her situation isn't. Most companies her size have one person doing what should be a team's job. They enable GuardDuty and call it security. They pass audits while attackers move through their infrastructure. The tools work. The gap is always human — not enough people, not enough time, not enough authority to fix what they can see.

If you recognized the techniques in this book, you're probably that person. Build the detections. Automate the responses. Push for temporary access. And hire a second engineer before you need one.

The tools Maya built exist. Search for them.

---

Friday. 11:47 PM. Somewhere with good Wi-Fi.

The admin of Cerberus Market — "The Professional's Exchange," according to the landing page nobody believed — was having a bad night. A buyer had left a one-star review on a batch of Shopify API keys. "Expired within 24 hours. Unacceptable for the price point." The admin typed a response with the weary patience of a customer service rep at a company that happened to be a federal crime: "All sales are final. Please review our freshness guarantee before purchasing."

He refunded them anyway. Reputation mattered, even here.

The K-drama on his second monitor was getting good — the lead had just discovered her business partner was embezzling — but he paused it. New listing notification. Priority seller.

He clicked through.

```
LISTING #4,891
Category: CI/CD Pipeline Access
Organization: [REDACTED] — Healthcare SaaS Platform
Pipeline: GitHub Actions → Production
Deployment footprint: ~400 hospital systems (US)
Asset: RSA-4096 code signing key (expires 2027)
Includes: Workflow files, deploy credentials, artifact registry token
Verification: Seller demonstrated signed artifact acceptance in staging environment
Price: Negotiable
```

The admin stopped chewing his ramen.

This wasn't API keys to some startup's sandbox account. This was the key that signed software hospitals trusted. Software that ran on machines connected to patient networks, pharmacy dispensing systems, EHR platforms. Every update signed with this key would install automatically. Routine maintenance. Trusted source.

Four hundred hospitals. One signing key. Zero questions asked at the other end.

He should take it down. That was the smart move. Law enforcement ignored credential listings — they were noise, thousands per week. But healthcare made headlines. Headlines brought task forces. Task forces killed marketplaces.

His hand moved toward the moderation panel.

A notification chimed. Someone had entered the listing's private chat. A buyer. He checked their profile: account created two years ago, one previous purchase.

He pulled up the transaction history.

Purchased: AWS IAM access key. Organization: Meridian Financial. Date: February 2025.

The buyer's message was one word:

*"Price."*

The admin looked at the moderation panel. Looked at the listing. Looked at the buyer's history. Looked at the K-drama, frozen on the embezzlement reveal.

He put his headphones back on and pressed play.
