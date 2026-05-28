# Marketplace Monetization & Economics

Capacium's marketplace fee model is designed to attract publishers during the cold-start phase while remaining competitive with major developer tool marketplaces at scale.

## Competitive Landscape

Developer tool marketplaces cluster into distinct fee regions:

| Marketplace | Commission | Category |
|------------|-----------|----------|
| Azure Marketplace | 3% flat | Cloud infrastructure |
| AWS Marketplace (SaaS) | 3% (1.5% renewals) | Cloud infrastructure |
| Google Cloud Marketplace | 3% (1.5% renewals) | Cloud infrastructure |
| Freemius | 4.7–7% progressive | WordPress monetization |
| JetBrains Marketplace | 15% | Developer tools |
| Shopify App Store | 0% first $1M, then 15% | Developer tools |
| Apple App Store | 15–30% | Consumer apps |
| Envato / ThemeForest | 50% (from July 2026) | Creative assets |

For a capability registry targeting developers and AI practitioners, the **5–10% range** is the competitive sweet spot. Below 5% makes the business unviable without massive scale. Above 15% requires distribution power comparable to Apple or JetBrains.

## Capacium's Progressive Fee Model

Fees are calculated on publisher lifetime revenue tier thresholds (marginal, like tax brackets):

| Revenue Tier | Platform Fee | Payment Processing | Publisher Keeps |
|-------------|-------------|-------------------|-----------------|
| $0 – $10,000 | 0% | 2.5% | 97.5% |
| $10,001 – $100,000 | 10% | 2.5% | 87.5% |
| $100,001 – $1,000,000 | 7% | 2.5% | 90.5% |
| $1,000,000+ | 5% | 2.5% | 92.5% |

### Example Calculation

A publisher with $150,000 lifetime revenue:

```
First $10,000:     0% platform fee = $0
Next $90,000:      10% platform fee = $9,000
Remaining $50,000: 7% platform fee = $3,500
Total platform fee: $12,500
Plus 2.5% processing on all $150,000: $3,750
Publisher keeps: $133,750 (89.2%)
```

### Why Progressive Tiers?

1. **Cold-start incentive** — The 0% tier removes all friction for early publishers, following the Shopify pattern ($0 fee on first $1M lifetime). A publisher with a $4.99/month subscription and 5 customers pays nothing to the platform until they grow.

2. **Competitive at growth** — At the Growth tier (10%), the effective rate of 12.5% (including processing) is below JetBrains (15%) and significantly below Apple (15–30%) or Envato (50%).

3. **Rewards scale** — The declining fee at higher tiers (7% → 5%) rewards successful publishers and prevents defection to direct sales channels once publishers build their own audience.

## Publisher-Controlled Pricing

Publishers set their own prices entirely. Capacium never controls or overrides publisher pricing — following the successful model of JetBrains, Shopify, and Azure (and deliberately avoiding the OpenAI GPT Store anti-pattern of platform-controlled payouts).

### Supported Pricing Models

| Model | Description | Billing |
|-------|-------------|---------|
| **Free** | No charge | None |
| **One-time** | Single purchase | One-time charge |
| **Subscription (monthly)** | Recurring monthly | Monthly billing |
| **Subscription (yearly)** | Annual billing | Annual billing |
| **Usage-based** | Per-execution / per-unit | Metered monthly |

### Manifest Pricing Declaration

```yaml
kind: skill
name: premium-linter
pricing:
  model: subscription
  plans:
    - name: monthly
      price: 4.99
      currency: USD
      interval: month
    - name: yearly
      price: 49.99
      currency: USD
      interval: year
  trial:
    days: 14
    requireCard: false
```

## Payout Schedule

| Condition | Frequency | Minimum |
|-----------|-----------|---------|
| Standard publishers | Monthly (net-30) | $10 |
| Year-end guarantee | December 31 | $0 (flush all balances) |

The $10 minimum payout is intentionally low during the cold-start phase to avoid frustrating early publishers with small earnings. The year-end flush (adopted from JetBrains) ensures no publisher funds are held indefinitely.

## Payment Infrastructure: Stripe Connect

Capacium's marketplace uses **Stripe Connect** for publisher payouts and payment processing. This provides:

- Standard connected account onboarding (identity verification)
- Payment processing at 2.5% (passed through transparently)
- License key generation at purchase time (JWT with Ed25519)
- `cap install` verifies license keys at download for paid capabilities
- Direct publisher access to Stripe Dashboard for initial analytics

## Cold-Start Strategy

Two-sided marketplaces face a chicken-and-egg problem: consumers won't come without capabilities, and publishers won't invest without an audience.

Capacium's strategy applies five proven tactics:

1. **Subsidize supply first** — 0% fee tier removes all friction for early publishers
2. **Provide SaaS value before marketplace value** — Licensing, analytics, and tooling justify the platform relationship even at low volumes (Freemius pattern)
3. **Curate, don't aggregate** — Launch with 20–30 high-quality capabilities rather than opening floodgates
4. **Seed with first-party capabilities** — Reference implementations that demonstrate the platform
5. **Progressive fee reduction** — Fees decrease as publishers succeed, creating alignment

## Bootstrapping Economics Model

| Phase | Months | Publishers | Monthly GMV | Platform Revenue |
|-------|--------|-----------|-------------|-----------------|
| Seed | 1–6 | 5–15 invited | $1K–$5K | $0 (free tier) |
| Early | 7–12 | 30–75 | $10K–$50K | $800–$4K |
| Growth | 13–18 | 100–250 | $50K–$200K | $4K–$16K |
| Scale | 19–24 | 300–500 | $200K–$500K | $16K–$40K |

Platform revenue is expected to be minimal during the first 12–18 months due to the 0% cold-start tier. This is intentional — the goal is publisher acquisition and catalog depth, not immediate monetization.

## Buyer Trust Framework

| Mechanism | Protection |
|-----------|-----------|
| Trust pipeline | Every listed capability has a trust state (verified, signed) |
| Secure licensing | License keys generated server-side, verified at install |
| Payment via Stripe | All transactions processed through Stripe (PCI-DSS compliant) |
| Composite trust scores | Multi-dimensional quality assessment (schema, security, maintenance) |
| Public reviews | Planned for growth phase |
| Refund policy | 14-day refund window on all paid capabilities |

## Key Anti-Patterns Avoided

1. **Platform-controlled pricing** — Capacium never sets publisher prices (unlike OpenAI GPT Store)
2. **Opaque engagement-based payouts** — Publishers see exact transaction economics
3. **Annual commission-free threshold resets** — Capacium uses lifetime caps, not annual resets
4. **Aggregator-level fees** — 50%+ commissions are Envato's model, not Capacium's
