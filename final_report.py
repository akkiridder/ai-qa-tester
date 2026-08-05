import json
from pathlib import Path
from collections import defaultdict

db_path = Path('data/database.json')
with open(db_path) as f:
    db = json.load(f)

test_cases = db.get('test_cases', {})
all_tests = [tc for tc in test_cases.values() if tc.get('projectId') == '59ad20d90fcf48c3']
ai_tests = [tc for tc in all_tests if tc.get('source') == 'ai-discovery']
supp_tests = [tc for tc in all_tests if tc.get('source') == 'manual-comprehensive']

print('='*80)
print('FINAL TEST COVERAGE REPORT')
print('='*80)
print()
print(f'AI Discovery Tests: {len(ai_tests)}')
print(f'Supplemental Tests: {len(supp_tests)}')
print(f'Total Tests: {len(all_tests)}')
print()

# Group by category
by_category = defaultdict(list)
for tc in supp_tests:
    category = tc.get('category', 'Unknown')
    by_category[category].append(tc)

print('Supplemental Test Coverage:')
print('-'*80)
for category in sorted(by_category.keys()):
    count = len(by_category[category])
    print(f'[ADDED] {category}: {count} tests')
    tests_to_show = by_category[category][:2]
    for tc in tests_to_show:
        name = tc.get('name')
        print(f'        - {name}')
    if count > 2:
        print(f'        ... and {count-2} more')

print()
print('='*80)
print('COVERAGE IMPROVEMENT')
print('='*80)
print()
print('BEFORE (AI-Generated Only):')
print('  - Account (1)')
print('  - Critical Flows (16)')
print('  - Negative/Edge (17)')
print('  - Product (16)')
print('  - Total: 50 tests covering 4 basic categories')
print()
print('AFTER (AI + Comprehensive Supplemental):')
print('  - Account (1)')
print('  - Critical Flows (16)')
print('  - Negative/Edge (17)')
print('  - Product (16)')
print('  + Registration Page (5)')
print('  + Login Account Recovery (4)')
print('  + Product Listing Page PLP (6)')
print('  + Product Display Page PDP (6)')
print('  + Mini-Cart Drawer (4)')
print('  + Security Penetration Testing (4)')
print('  + Performance Load Testing (4)')
print(f'  - Total: {len(all_tests)} tests covering 11 categories')
print()
print('KEY ADDITIONS:')
print('  [+] Security: SQL Injection, XSS, IDOR, Rate Limiting tests')
print('  [+] Performance: LCP, 3G throttling, Infinite scroll, Debounce')
print('  [+] PLP: Sorting, Multi-filter, Pagination, State Persistence')
print('  [+] PDP: Variants, Gallery, Inventory, Reviews, Dynamic Pricing')
print('  [+] Registration: Sign-up, Validation, Password Strength')
print('  [+] Login: Credentials, Lockout, Password Reset')
print()
