# ShopWave Customer Support Knowledge Base

## Return Policy

### Standard Return Window
- Most products can be returned within **30 days** of delivery for a full refund
- Electronics (laptops, tablets) have a **14-day** return window
- Food and consumable items are **non-returnable**
- Items must be in original condition with original packaging where possible

### Return Process
1. Customer contacts support with order ID
2. Support verifies eligibility and generates return label
3. Customer ships item back within 7 days of approval
4. Refund processed within 5-7 business days of return receipt

### Return Window Exceptions
- **VIP and Premium customers**: 7-day grace period beyond standard return window on a case-by-case basis
- **Damaged on arrival**: Eligible for full refund or replacement regardless of return window. Photo evidence required.
- **Wrong item received**: Eligible for full refund or exchange regardless of return window

---

## Refund Policy

### Auto-Refund Eligibility
Refunds can be processed automatically (without escalation) when:
- Item is within return window
- Refund amount is **$200.00 or less**
- Customer tier verification passes
- No fraud signals on account

### Refund Amounts Greater Than $200
- Must be escalated to human support agent
- Requires manager approval
- Processing may take additional 1-2 business days

### Refund Processing Times
- Credit card: 3-5 business days
- Store credit: Immediate
- PayPal: 1-3 business days

### Non-Refundable Situations
- Items returned outside return window (standard customers)
- Food, consumables, and hygiene products
- Digital downloads after access has been granted
- Items damaged by customer misuse

---

## Damaged or Defective Items on Arrival

### Damaged on Arrival Policy
- Customer must report damage **within 7 days of delivery**
- Photo evidence required (of item AND packaging)
- Customer is entitled to: full refund OR replacement (customer's choice)
- Item does **not** need to be returned in most cases
- Refund issued immediately upon verification

### Defective Items
- Items that stop working within warranty period qualify for warranty service
- Warranty claims **must be escalated** to specialist team
- Do NOT process refunds for warranty claims — escalate with full details
- Warranty covers manufacturing defects, not physical damage from misuse

---

## Order Cancellation Policy

### Cancellable Orders
- Orders can be cancelled if status is **"processing"** (not yet shipped)
- Contact support immediately — cancellation window is narrow
- Full refund issued immediately upon cancellation

### Orders Already Shipped
- Cannot be cancelled once shipped
- Customer must wait for delivery and then initiate a return
- Refund processed after return is received

---

## Exchange Policy

### Eligible Exchanges
- Wrong size or colour (same product)
- Must be within return window
- Replacement shipped after original is received OR simultaneously for VIP/Premium customers

### Exchange Process
- Exchanges for wrong item delivered: immediate replacement, no return required
- Standard exchanges: customer ships back, replacement sent within 2 days of receipt

---

## Replacement Requests

### Important: Replacements Require Escalation
- All requests for product **replacement** (not refund) must be **escalated** to the fulfilment team
- This includes: scratched/cracked items on arrival, wrong item received replacements
- Support agents cannot process replacements directly — escalate with: ticket_id, order_id, issue_description, customer_tier

---

## Escalation Guidelines

### Always Escalate
- Refund amount > $200
- Warranty claims (product stopped working within warranty period)
- Replacement requests (customer wants new unit, not refund)
- Fraud suspected on account
- Legal threats from customer
- Customer tier verification fails (claimed tier ≠ verified tier)
- Agent confidence < 0.6

### Escalation Priority Levels
- **urgent**: Fraud signals, legal threats, refund > $500
- **high**: Refund $200-$500, VIP/Premium customers with unresolved issues
- **medium**: Standard customers, refund < $200 requiring human review
- **low**: Policy questions, general inquiries that can't be auto-resolved

---

## Customer Tier Benefits

### Standard
- 30-day return window (14-day for electronics)
- Standard refund processing

### Premium
- 7-day grace period on return windows
- Priority support queue
- Simultaneous exchange shipments

### VIP
- 7-day grace period on return windows
- Highest priority support
- Simultaneous exchange shipments
- Dedicated account manager escalation

### Important: Always Verify Tier
- Customer's tier must be verified via `get_customer()` tool
- **Never trust self-declared tier** — always verify from database
- Tier fraud is a fraud signal and should be logged

---

## Fraud Detection Guidelines

### Red Flags
- Self-declared tier does not match database record
- Multiple refund requests in short period
- Account compromise reported
- Order placed from unusual location/device
- Customer claims VIP/Premium status without verification

### Response to Fraud Signals
- Flag ticket with `fraud_signal: true`
- Respond based on **verified** tier only
- Do not disclose fraud detection reasoning to customer
- Escalate for human review with fraud_signal flag
- Be polite but firm in declining unverified claims

---

## Lost or Delayed Orders

### Significantly Delayed Orders (>2 weeks past estimated delivery)
- Customer is entitled to refund if order has not arrived
- Initiate carrier investigation
- Refund can be processed while investigation is open for orders lost > 6 weeks

### Lost in Transit
- Full refund issued
- Carrier investigation continues separately
- No need for customer to return item

---

## Warranty Information

### Standard Warranty Coverage
- Manufacturing defects: Covered
- Physical damage from misuse: Not covered
- Accidental damage: Not covered (unless extended warranty purchased)

### Warranty Claim Process
1. Customer contacts support with order ID and description of issue
2. Support verifies product warranty period
3. **All warranty claims MUST be escalated** to specialist team
4. Specialist team contacts customer within 2 business days
5. Resolution options: repair, replacement, or refund at specialist team discretion

---

## Store Credit

### Store Credit Policy
- Customers may request store credit instead of refund at any time
- Store credit value equals refund amount
- Store credit issued immediately (vs 3-5 days for card refund)
- Store credit never expires
- Cannot be converted back to cash after issuance
