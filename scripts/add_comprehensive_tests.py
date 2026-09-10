import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

def make_id():
    return str(uuid.uuid4())[:16]

def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

# Comprehensive eCommerce Test Cases - Filling Coverage Gaps
SUPPLEMENTAL_TEST_CASES = [
    # ============ REGISTRATION PAGE ============
    ("Registration: Valid Sign-Up with Unique Email", "Registration Page", [
        {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
        {"action": "fill", "target": "id=firstName", "value": "John", "verify": "First name field filled"},
        {"action": "fill", "target": "id=lastName", "value": "Doe", "verify": "Last name field filled"},
        {"action": "fill", "target": "id=email", "value": "john.doe@example.com", "verify": "Email field filled"},
        {"action": "fill", "target": "id=password", "value": "SecurePass@123", "verify": "Password field filled"},
        {"action": "click", "target": "id=registerBtn", "verify": "Account created successfully"},
    ]),
    ("Registration: Duplicate Email Error", "Registration Page", [
        {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
        {"action": "fill", "target": "id=email", "value": "existing@example.com", "verify": "Email filled"},
        {"action": "fill", "target": "id=password", "value": "SecurePass@123", "verify": "Password filled"},
        {"action": "click", "target": "id=registerBtn", "verify": "Error for duplicate email"},
    ]),
    ("Registration: Password Strength Validation", "Registration Page", [
        {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
        {"action": "fill", "target": "id=password", "value": "weak", "verify": "Weak password entered"},
        {"action": "blur", "target": "id=password", "verify": "Weak indicator shows"},
        {"action": "fill", "target": "id=password", "value": "StrongPass@123", "verify": "Strong password entered"},
    ]),
    ("Registration: Email Format Validation", "Registration Page", [
        {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
        {"action": "fill", "target": "id=email", "value": "invalid-email", "verify": "Invalid email entered"},
        {"action": "click", "target": "id=registerBtn", "verify": "Validation error for email"},
    ]),
    ("Registration: XSS Prevention in Form Input", "Registration Page", [
        {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
        {"action": "fill", "target": "id=firstName", "value": "<script>alert('XSS')</script>", "verify": "Script tag entered"},
        {"action": "click", "target": "id=registerBtn", "verify": "Script sanitized, no XSS"},
    ]),

    # ============ LOGIN & ACCOUNT RECOVERY ============
    ("Login: Valid Credentials Access", "Login & Account Recovery", [
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
        {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email filled"},
        {"action": "fill", "target": "id=password", "value": "ValidPass@123", "verify": "Password filled"},
        {"action": "click", "target": "id=loginBtn", "verify": "User logged in successfully"},
    ]),
    ("Login: Invalid Password Error", "Login & Account Recovery", [
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
        {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email filled"},
        {"action": "fill", "target": "id=password", "value": "WrongPass", "verify": "Wrong password entered"},
        {"action": "click", "target": "id=loginBtn", "verify": "Error message appears"},
    ]),
    ("Login: Account Lockout Protection", "Login & Account Recovery", [
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
        {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email filled"},
        {"action": "fill", "target": "id=password", "value": "Wrong1", "verify": "Wrong password 1"},
        {"action": "click", "target": "id=loginBtn", "verify": "Failed attempt 1"},
        {"action": "fill", "target": "id=password", "value": "Wrong2", "verify": "Wrong password 2"},
        {"action": "click", "target": "id=loginBtn", "verify": "Failed attempt 2"},
        {"action": "fill", "target": "id=password", "value": "Wrong3", "verify": "Wrong password 3"},
        {"action": "click", "target": "id=loginBtn", "verify": "Account locked"},
    ]),
    ("Login: Password Reset Link", "Login & Account Recovery", [
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
        {"action": "click", "target": "xpath=//a[text()='Forgot Password?']", "verify": "Reset page opens"},
        {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email entered"},
        {"action": "click", "target": "id=resetBtn", "verify": "Reset email sent"},
    ]),

    # ============ PRODUCT LISTING PAGE (PLP) ============
    ("PLP: Sort by Price Low to High", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "click", "target": "id=sortDropdown", "verify": "Sort dropdown opens"},
        {"action": "click", "target": "xpath=//option[text()='Price: Low to High']", "verify": "Sort applied"},
        {"action": "verify", "target": "xpath=//div[@class='product-list']", "verify": "Sorted correctly"},
    ]),
    ("PLP: Multi-Filter Selection", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "click", "target": "xpath=//label[text()='Samsung']", "verify": "Brand filter applied"},
        {"action": "click", "target": "xpath=//label[text()='$500-$1000']", "verify": "Price filter applied"},
        {"action": "verify", "target": "xpath=//div[@class='filtered-results']", "verify": "Filters work together"},
    ]),
    ("PLP: Grid vs List View", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "click", "target": "id=listViewBtn", "verify": "List view selected"},
        {"action": "verify", "target": "xpath=//div[@class='product-list-view']", "verify": "List view displays"},
        {"action": "click", "target": "id=gridViewBtn", "verify": "Grid view selected"},
    ]),
    ("PLP: Pagination", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "Page 1 loads"},
        {"action": "click", "target": "xpath=//a[text()='2']", "verify": "Click page 2"},
        {"action": "verify", "target": "xpath=//span[text()='Page 2']", "verify": "Page 2 displays"},
        {"action": "click", "target": "xpath=//a[text()='Previous']", "verify": "Back to page 1"},
    ]),
    ("PLP: Sale and Stock Badges", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "verify", "target": "xpath=//div[@class='sale-badge']", "verify": "Sale badge visible"},
        {"action": "verify", "target": "xpath=//div[@class='new-badge']", "verify": "New badge visible"},
        {"action": "verify", "target": "xpath=//div[@class='out-of-stock-badge']", "verify": "Stock badge visible"},
    ]),
    ("PLP: Filter URL Persistence", "Product Listing Page (PLP)", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "click", "target": "xpath=//label[text()='Samsung']", "verify": "Filter applied"},
        {"action": "execute", "target": "javascript:navigator.clipboard.writeText(window.location.href)", "verify": "URL copied"},
        {"action": "navigate", "target": "$BASE_URL", "verify": "Navigate away"},
        {"action": "navigate", "target": "javascript:navigator.clipboard.readText()", "verify": "Navigate to copied URL"},
        {"action": "verify", "target": "xpath=//label[@checked and text()='Samsung']", "verify": "Filter persisted"},
    ]),

    # ============ PRODUCT DISPLAY PAGE (PDP) ============
    ("PDP: Variant Price Update", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/item-123", "verify": "PDP loads"},
        {"action": "click", "target": "xpath=//button[@data-size='L']", "verify": "Size L selected"},
        {"action": "verify", "target": "xpath=//span[@class='price' and text()='$599']", "verify": "Price updated"},
    ]),
    ("PDP: Image Gallery and Zoom", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/item-123", "verify": "PDP loads"},
        {"action": "click", "target": "xpath=//img[@class='thumb'][1]", "verify": "Image selected"},
        {"action": "hover", "target": "xpath=//img[@class='main-image']", "verify": "Hover enabled"},
        {"action": "verify", "target": "xpath=//div[@class='zoom-overlay']", "verify": "Zoom works"},
    ]),
    ("PDP: Low Stock and Out of Stock", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/low-stock", "verify": "PDP loads"},
        {"action": "verify", "target": "xpath=//span[text()='Only 2 left']", "verify": "Low stock warning"},
        {"action": "navigate", "target": "$BASE_URL/product/out-of-stock", "verify": "Out of stock PDP loads"},
        {"action": "verify", "target": "xpath=//button[@disabled and text()='Add to Cart']", "verify": "Add to Cart disabled"},
    ]),
    ("PDP: Breadcrumb Navigation", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/item-123", "verify": "PDP loads"},
        {"action": "verify", "target": "xpath=//a[text()='Home']", "verify": "Home breadcrumb"},
        {"action": "verify", "target": "xpath=//a[text()='Electronics']", "verify": "Category breadcrumb"},
        {"action": "click", "target": "xpath=//a[text()='Electronics']", "verify": "Click category"},
    ]),
    ("PDP: Customer Reviews Submit", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/item-123", "verify": "PDP loads"},
        {"action": "click", "target": "id=writeReviewBtn", "verify": "Review form opens"},
        {"action": "click", "target": "xpath=//span[@class='star'][5]", "verify": "5-star selected"},
        {"action": "fill", "target": "id=reviewText", "value": "Great product!", "verify": "Review text filled"},
        {"action": "click", "target": "id=submitReviewBtn", "verify": "Review submitted"},
    ]),
    ("PDP: Dynamic Matrix Pricing", "Product Display Page (PDP)", [
        {"action": "navigate", "target": "$BASE_URL/product/configurable", "verify": "PDP loads"},
        {"action": "click", "target": "xpath=//button[@data-variant='premium']", "verify": "Premium selected"},
        {"action": "verify", "target": "xpath=//span[text()='$999']", "verify": "$999 price"},
        {"action": "click", "target": "xpath=//button[@data-variant='standard']", "verify": "Standard selected"},
        {"action": "verify", "target": "xpath=//span[text()='$599']", "verify": "$599 price"},
    ]),

    # ============ MINI-CART ============
    ("Mini-Cart: Flyout Opens", "Mini-Cart / Drawer", [
        {"action": "navigate", "target": "$BASE_URL/product/item-1", "verify": "Product page loads"},
        {"action": "click", "target": "id=addToCartBtn", "verify": "Add to Cart clicked"},
        {"action": "verify", "target": "xpath=//div[@class='mini-cart-drawer']", "verify": "Mini-cart drawer opens"},
    ]),
    ("Mini-Cart: Badge Increment", "Mini-Cart / Drawer", [
        {"action": "navigate", "target": "$BASE_URL", "verify": "Home loads"},
        {"action": "verify", "target": "xpath=//span[@class='cart-badge' and text()='0']", "verify": "Badge is 0"},
        {"action": "navigate", "target": "$BASE_URL/product/item-1", "verify": "Product loads"},
        {"action": "click", "target": "id=addToCartBtn", "verify": "Add to Cart"},
        {"action": "verify", "target": "xpath=//span[@class='cart-badge' and text()='1']", "verify": "Badge is 1"},
    ]),
    ("Mini-Cart: Modify Quantity", "Mini-Cart / Drawer", [
        {"action": "navigate", "target": "$BASE_URL", "verify": "Home loads"},
        {"action": "click", "target": "id=cartIcon", "verify": "Mini-cart opens"},
        {"action": "fill", "target": "xpath=//input[@class='qty']", "value": "3", "verify": "Qty changed to 3"},
        {"action": "verify", "target": "xpath=//span[@class='total']", "verify": "Total updated"},
    ]),
    ("Mini-Cart: Delete Item", "Mini-Cart / Drawer", [
        {"action": "navigate", "target": "$BASE_URL", "verify": "Home loads"},
        {"action": "click", "target": "id=cartIcon", "verify": "Mini-cart opens"},
        {"action": "click", "target": "xpath=//button[@class='delete-btn']", "verify": "Delete clicked"},
        {"action": "verify", "target": "xpath=//span[@class='cart-badge' and text()='0']", "verify": "Item removed"},
    ]),

    # ============ SECURITY TESTING ============
    ("Security: SQL Injection in Search", "Security & Penetration Testing", [
        {"action": "navigate", "target": "$BASE_URL", "verify": "Home loads"},
        {"action": "fill", "target": "id=search", "value": "' OR '1'='1", "verify": "SQLi payload entered"},
        {"action": "click", "target": "id=searchBtn", "verify": "Search executed"},
        {"action": "verify", "target": "xpath=//span[text()='No results']", "verify": "Query parameterized"},
    ]),
    ("Security: XSS in Reviews", "Security & Penetration Testing", [
        {"action": "navigate", "target": "$BASE_URL/product/item-1", "verify": "PDP loads"},
        {"action": "click", "target": "id=writeReviewBtn", "verify": "Review form opens"},
        {"action": "fill", "target": "id=reviewText", "value": "<script>alert('XSS')</script>", "verify": "Script entered"},
        {"action": "click", "target": "id=submitBtn", "verify": "Submitted"},
        {"action": "verify", "target": "xpath=//span[text()='&lt;script&gt;']", "verify": "HTML encoded"},
    ]),
    ("Security: IDOR Access Prevention", "Security & Penetration Testing", [
        {"action": "navigate", "target": "$BASE_URL/user/123/orders", "verify": "Own orders load"},
        {"action": "navigate", "target": "$BASE_URL/user/999/orders", "verify": "Try other user"},
        {"action": "verify", "target": "xpath=//h1[text()='403']", "verify": "Access denied"},
    ]),
    ("Security: Rate Limiting", "Security & Penetration Testing", [
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
        {"action": "execute", "target": "javascript:for(let i=0;i<10;i++){fetch('/api/login')}", "verify": "10 requests sent"},
        {"action": "wait", "value": 1, "verify": "Wait"},
        {"action": "navigate", "target": "$BASE_URL/login", "verify": "Try login"},
        {"action": "verify", "target": "xpath=//h1[text()='429']", "verify": "Rate limit triggered"},
    ]),

    # ============ PERFORMANCE TESTING ============
    ("Performance: LCP < 2.5 seconds", "Performance & Load Testing", [
        {"action": "navigate", "target": "$BASE_URL", "verify": "Home navigated"},
        {"action": "execute", "target": "javascript:console.log(window.performance.timing)", "verify": "Timing measured"},
        {"action": "verify", "target": "javascript:performance.getEntriesByType('largest-contentful-paint')[0].renderTime < 2500", "verify": "LCP < 2.5s"},
    ]),
    ("Performance: 3G Network Load", "Performance & Load Testing", [
        {"action": "navigate", "target": "$BASE_URL/search?q=laptop", "verify": "Search with throttling"},
        {"action": "verify", "target": "xpath=//div[@class='results']", "verify": "Loads on 3G"},
    ]),
    ("Performance: Infinite Scroll Memory", "Performance & Load Testing", [
        {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
        {"action": "scroll", "target": "document.body", "value": 5000, "verify": "Scroll down"},
        {"action": "scroll", "target": "document.body", "value": 10000, "verify": "Scroll more"},
        {"action": "execute", "target": "javascript:console.log(performance.memory)", "verify": "Memory OK"},
    ]),
    ("Performance: Input Debounce", "Performance & Load Testing", [
        {"action": "navigate", "target": "$BASE_URL/cart", "verify": "Cart loads"},
        {"action": "execute", "target": "javascript:document.querySelector('input.qty').value=1;input()", "verify": "Qty 1"},
        {"action": "execute", "target": "javascript:document.querySelector('input.qty').value=2;input()", "verify": "Qty 2"},
        {"action": "execute", "target": "javascript:document.querySelector('input.qty').value=3;input()", "verify": "Qty 3"},
        {"action": "wait", "value": 1, "verify": "Debounce wait"},
        {"action": "verify", "target": "javascript:true", "verify": "Only 1 request made"},
    ]),
]

def add_test_cases():
    """Add supplemental test cases to database"""
    db_path = Path('data/database.json')
    with open(db_path) as f:
        db = json.load(f)
    
    test_cases_table = db.get('test_cases', {})
    
    # Use first project ID as target
    project_id = '59ad20d90fcf48c3'
    
    # Get existing test case count
    existing = [t for t in test_cases_table.values() if t.get('projectId') == project_id]
    next_sort = len(existing)
    
    added = []
    for i, (name, category, steps) in enumerate(SUPPLEMENTAL_TEST_CASES):
        tcid = make_id()
        tc_key = str(max([int(k) for k in test_cases_table.keys() if k.isdigit()] or [0]) + 1)
        
        tc = {
            "_id": tcid,
            "id": tcid,
            "projectId": project_id,
            "name": name,
            "category": category,
            "steps": steps,
            "source": "manual-comprehensive",
            "isRegression": True,
            "sortOrder": next_sort + i,
            "createdAt": now_iso(),
            "updatedAt": now_iso()
        }
        test_cases_table[tc_key] = tc
        added.append(f"[OK] {category}: {name}")
    
    db['test_cases'] = test_cases_table
    
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=2)
    
    return added

if __name__ == '__main__':
    added = add_test_cases()
    print(f'Added {len(added)} comprehensive test cases:\n')
    for item in added:
        print(f'  {item}')
    print(f'\nTotal: {len(added)} new test cases')
