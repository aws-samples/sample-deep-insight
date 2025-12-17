# Multi-Region Deployment Guide

> Supplementary guide for deploying to different AWS regions and accounts

**→ Back to [Main README](../../README.md)**

---

## 🎯 Overview

This guide covers the **AZ (Availability Zone) verification** required when deploying to different regions or accounts.

**Key Issue**: AZ names like `us-east-1a` are **account-specific** - the same name maps to different physical datacenters in different AWS accounts.

```
Account A:  us-east-1a → use1-az4 ✅ Supported
Account B:  us-east-1a → use1-az6 ❌ NOT Supported
```

---

## 📋 Supported Regions and AZ IDs

| Region | Code | Supported AZ IDs |
|--------|------|------------------|
| US East (N. Virginia) | `us-east-1` | `use1-az1`, `use1-az2`, `use1-az4` |
| US East (Ohio) | `us-east-2` | `use2-az1`, `use2-az2`, `use2-az3` |
| US West (Oregon) | `us-west-2` | `usw2-az1`, `usw2-az2`, `usw2-az3` |
| Asia Pacific (Mumbai) | `ap-south-1` | `aps1-az1`, `aps1-az2`, `aps1-az3` |
| Asia Pacific (Singapore) | `ap-southeast-1` | `apse1-az1`, `apse1-az2`, `apse1-az3` |
| Asia Pacific (Sydney) | `ap-southeast-2` | `apse2-az1`, `apse2-az2`, `apse2-az3` |
| Asia Pacific (Tokyo) | `ap-northeast-1` | `apne1-az1`, `apne1-az2`, `apne1-az4` |
| Europe (Ireland) | `eu-west-1` | `euw1-az1`, `euw1-az2`, `euw1-az3` |
| Europe (Frankfurt) | `eu-central-1` | `euc1-az1`, `euc1-az2`, `euc1-az3` |

---

## ✅ AZ Verification

### Run Before Every Deployment

```bash
cd production_deployment/scripts/phase1
./verify_agentcore_azs.sh <region>
```

### Example Output

```
Region: us-east-1

✅ us-east-1a → use1-az4 (SUPPORTED)
❌ us-east-1b → use1-az6 (NOT SUPPORTED)
✅ us-east-1c → use1-az1 (SUPPORTED)

Use these AZ names for deployment:
  AvailabilityZone1=us-east-1a
  AvailabilityZone2=us-east-1c
```

### Check Your AZ Mapping Manually

```bash
aws ec2 describe-availability-zones --region us-east-1 \
  --query 'AvailabilityZones[*].{Name:ZoneName, ID:ZoneId}' \
  --output table
```

---

## 🛠️ Troubleshooting

### "Unsupported Availability Zone"

**Cause**: AZ name maps to unsupported AZ ID in your account.

**Solution**: Run `./verify_agentcore_azs.sh <region>` and use only SUPPORTED AZs.

### Deployment Works in Account A, Fails in Account B

**Cause**: Same AZ name maps to different AZ IDs in different accounts.

**Solution**: Never copy AZ names between accounts. Always run verification for each account.

### "VPC Endpoint Not Available"

**Cause**: Region does not support AgentCore VPC mode.

**Solution**: Use one of the 9 supported regions listed above.

---

## 📝 Best Practices

- **Always verify AZs** before deploying to a new account or region
- **Document AZ mappings** for each account you deploy to
- **Use non-overlapping CIDRs** if deploying to multiple regions (e.g., `10.0.0.0/16`, `10.1.0.0/16`)
- **Test in development** before production deployment

---

**→ Back to [Main README](../../README.md)**
