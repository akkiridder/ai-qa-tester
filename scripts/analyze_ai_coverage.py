import json
from pathlib import Path
from collections import defaultdict

db_path = Path('data/database.json')
with open(db_path) as f:
    db = json.load(f)

test_cases = db.get('test_cases', {})
ai_tests = [tc for tc in test_cases.values() if tc.get('source') == 'ai-discovery' and tc.get('projectId') == '073d2488505b4bce']

print(f'Total AI-Discovery Test Cases for HME: {len(ai_tests)}\n')
print('='*80)

# Group by category
by_category = defaultdict(list)
for tc in ai_tests:
    category = tc.get('category', 'Unknown')
    by_category[category].append(tc)

# Print by category
for category in sorted(by_category.keys()):
    tests = by_category[category]
    print(f'\n{category} ({len(tests)} tests):')
    for tc in tests:
        print(f'  - {tc.get("name", "N/A")}')

print('\n' + '='*80)
print('\nCOVERAGE ANALYSIS:')
print('-'*80)

# Reference categories
reference_categories = {
    'Registration Page': ['Valid Sign-Up', 'Duplicate Email', 'Password Strength', 'Field Validations', 'Race Condition on Submit', 'Input Sanitization'],
    'Login & Account Recovery': ['Valid Login', 'Invalid Login', 'Password Reset', 'Account Lockout'],
    'My Account Dashboard': ['Profile Management', 'Address Book', 'Order History', 'Order Tracking'],
    'Home Page & Global Navigation': ['Header/Footer Links', 'Hero Banners', 'Localization Toggle', 'Responsive Layout'],
    'Search Results Page': ['Keyword Match', 'Partial/Typos', 'No Results State', 'Auto-Suggest', 'Stop-Words & Special Chars', 'Synonym Mapping'],
    'Product Listing Page (PLP)': ['Sorting Engine', 'Multi-Filter Selection', 'Grid vs List View', 'Pagination & Scroll', 'Badges & Labels', 'Facet Multi-Select', 'Filter State Persistence'],
    'Product Display Page (PDP)': ['Variant Switching', 'Media Gallery', 'Inventory Thresholds', 'Breadcrumb Trail', 'Reviews & Ratings', 'Complex Matrix Variant', 'Dynamic Pricing', 'Simultaneous Cart Race Condition'],
    'Mini-Cart / Drawer': ['Flyout Action', 'Badge Increment', 'Inline Edits', 'Checkout Routing', 'Session Handover'],
    'Shopping Cart Page': ['Subtotal Calculations', 'Cross-Tab Cache Sync', 'Save For Later', 'Empty Cart State', 'Tiered Promotion', 'Currency Conversion'],
    'Checkout & Shipping': ['Guest Flow', 'Address Validation', 'Delivery Tier Costs', 'Order Summary Panel', 'Address Split-Shipping', 'Browser Back-Button'],
    'Payment Gateway': ['Promo Coupon Validation', 'Successful Transaction', 'Declined Transaction', 'Session Expiry', 'Webhook Delay', '3D Secure Auth'],
    'Order Confirmation & Fulfillment': ['Success UI', 'Email/SMS Trigger', 'Analytics Tracking', 'Downstream ERP Sync'],
    'Security & Penetration Testing': ['SQL Injection', 'XSS', 'IDOR', 'Price Tampering', 'Promo Code Race Condition', 'Session Fixation', 'Token Lifetime', 'Rate Limiting', 'PII Log Inspection', 'PCI-DSS'],
    'Performance & Load Testing': ['Core Web Vitals', 'Flash Sale Load', 'Soak/Stability', 'Spike Load', 'Database & Index', 'Infinite Scroll', 'Debounce Throttle', 'API Timeout Recovery', 'CDN Efficiency'],
}

print('\nCovered Categories:')
for cat in sorted(by_category.keys()):
    print(f'  ✓ {cat} ({len(by_category[cat])} tests)')

print('\n\nMissing/Under-Covered Categories:')
for cat in sorted(reference_categories.keys()):
    if cat not in by_category or len(by_category[cat]) == 0:
        print(f'  ✗ {cat} (0 tests)')
    elif len(by_category[cat]) < 3:
        print(f'  ⚠ {cat} ({len(by_category[cat])} tests - needs more)')
