import json
from pathlib import Path
from collections import defaultdict

db_path = Path('data/database.json')
with open(db_path) as f:
    db = json.load(f)

test_cases = db.get('test_cases', {})
ai_tests = [tc for tc in test_cases.values() if tc.get('source') == 'ai-discovery' and tc.get('projectId') == '59ad20d90fcf48c3']

print(f'Total AI-Discovery Test Cases: {len(ai_tests)}\n')
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
reference_categories = [
    'Registration Page',
    'Login & Account Recovery',
    'My Account Dashboard',
    'Home Page & Global Navigation',
    'Search Results Page',
    'Product Listing Page (PLP)',
    'Product Display Page (PDP)',
    'Mini-Cart / Drawer',
    'Shopping Cart Page',
    'Checkout & Shipping',
    'Payment Gateway',
    'Order Confirmation & Fulfillment',
    'Security & Penetration Testing',
    'Performance & Load Testing',
]

print('\nCovered Categories:')
covered = set()
for cat in sorted(by_category.keys()):
    print(f'  ✓ {cat} ({len(by_category[cat])} tests)')
    covered.add(cat)

print('\n\nMissing/Under-Covered Categories:')
for cat in reference_categories:
    if cat not in covered:
        print(f'  ✗ {cat} (0 tests - NOT COVERED)')
    elif len(by_category[cat]) < 3:
        print(f'  ⚠ {cat} ({len(by_category[cat])} tests - needs more coverage)')
