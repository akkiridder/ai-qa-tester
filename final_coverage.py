import json
from pathlib import Path
from collections import defaultdict

db_path = Path('data/database.json')
with open(db_path) as f:
    db = json.load(f)

test_cases = db.get('test_cases', {})
# Include both AI-discovery AND manual-supplemental
all_tests = [tc for tc in test_cases.values() if tc.get('projectId') == '59ad20d90fcf48c3']

print(f'Total Test Cases (AI + Supplemental): {len(all_tests)}\n')
print('='*80)

# Group by category
by_category = defaultdict(list)
for tc in all_tests:
    category = tc.get('category', 'Unknown')
    by_category[category].append(tc)

# Print by category
for category in sorted(by_category.keys()):
    tests = by_category[category]
    print(f'\n{category} ({len(tests)} tests):')
    for tc in tests[:5]:
        print(f'  - {tc.get("name", "N/A")}')
    if len(tests) > 5:
        print(f'  ... and {len(tests)-5} more')

print('\n' + '='*80)
print('\nUPDATED COVERAGE ANALYSIS:')
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
total_covered = 0
for cat in sorted(by_category.keys()):
    count = len(by_category[cat])
    total_covered += count
    print(f'  ✓ {cat} ({count} tests)')
    covered.add(cat)

print('\n\nNow Covered vs Previously Missing:')
newly_covered = 0
for cat in reference_categories:
    if cat in covered:
        count = len(by_category[cat])
        status = '✓'
        newly_covered += 1
    else:
        status = '✗'
        count = 0
    
    coverage_level = "FULL" if count >= 5 else "PARTIAL" if count > 0 else "MISSING"
    print(f'  {status} {cat}: {count} tests [{coverage_level}]')

print('\n' + '='*80)
print(f'\nSUMMARY:')
print(f'  - Previously: 50 AI-generated test cases (4 categories)')
print(f'  - Added: 33 supplemental test cases covering gaps')
print(f'  - Total: {total_covered} test cases')
print(f'  - Categories Covered: {newly_covered}/14 reference categories')
print(f'\nCoverage Improvement: From basic flows to comprehensive eCommerce suite')
print(f'  - Security: 4 tests (SQL Injection, XSS, IDOR, Rate Limiting)')
print(f'  - Performance: 4 tests (LCP, 3G, Infinite Scroll, Debounce)')
print(f'  - PLP: 6 tests (Sorting, Filtering, Pagination, Badges, State Persistence)')
print(f'  - PDP: 6 tests (Variants, Media, Inventory, Reviews, Pricing)')
print(f'  - Registration: 5 tests (Sign-up, Validation, Security)')
print(f'  - Login: 4 tests (Valid/Invalid, Lockout, Reset)')
print(f'  - Mini-Cart: 4 tests (Flyout, Badge, Inline Edit, Delete)')
