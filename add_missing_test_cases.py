import json
import uuid
from datetime import datetime
from pathlib import Path

def make_id():
    return str(uuid.uuid4())[:16]

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

# Comprehensive eCommerce Test Cases - Filling Coverage Gaps
SUPPLEMENTAL_TEST_CASES = [
    # ============ REGISTRATION PAGE ============
    {
        "name": "Registration: Valid Sign-Up with Unique Email",
        "category": "Registration Page",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
            {"action": "fill", "target": "id=firstName", "value": "John", "verify": "First name field filled"},
            {"action": "fill", "target": "id=lastName", "value": "Doe", "verify": "Last name field filled"},
            {"action": "fill", "target": "id=email", "value": "john.doe@example.com", "verify": "Email field filled"},
            {"action": "fill", "target": "id=password", "value": "SecurePass@123", "verify": "Password field filled"},
            {"action": "fill", "target": "id=confirmPassword", "value": "SecurePass@123", "verify": "Confirm password filled"},
            {"action": "click", "target": "id=registerBtn", "verify": "Account created successfully"},
        ]
    },
    {
        "name": "Registration: Duplicate Email Error Handling",
        "category": "Registration Page",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
            {"action": "fill", "target": "id=email", "value": "existing@example.com", "verify": "Email field filled"},
            {"action": "fill", "target": "id=password", "value": "SecurePass@123", "verify": "Password field filled"},
            {"action": "click", "target": "id=registerBtn", "verify": "Error message appears for duplicate email"},
        ]
    },
    {
        "name": "Registration: Password Strength Validation",
        "category": "Registration Page",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
            {"action": "fill", "target": "id=password", "value": "weak", "verify": "Weak password entered"},
            {"action": "blur", "target": "id=password", "verify": "Password strength indicator shows weak"},
            {"action": "fill", "target": "id=password", "value": "StrongPass@123!", "verify": "Strong password entered"},
            {"action": "blur", "target": "id=password", "verify": "Password strength indicator shows strong"},
        ]
    },
    {
        "name": "Registration: Field Validation - Invalid Email Format",
        "category": "Registration Page",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
            {"action": "fill", "target": "id=email", "value": "invalid-email", "verify": "Invalid email entered"},
            {"action": "click", "target": "id=registerBtn", "verify": "Validation error appears for invalid email"},
        ]
    },
    {
        "name": "Registration: Input Sanitization - XSS Prevention",
        "category": "Registration Page",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/register", "verify": "Registration page loads"},
            {"action": "fill", "target": "id=firstName", "value": "<script>alert('XSS')</script>", "verify": "Script tag entered"},
            {"action": "click", "target": "id=registerBtn", "verify": "Script tag sanitized, no XSS executed"},
        ]
    },
    
    # ============ LOGIN & ACCOUNT RECOVERY ============
    {
        "name": "Login: Valid Credentials - Successful Access",
        "category": "Login & Account Recovery",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
            {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email field filled"},
            {"action": "fill", "target": "id=password", "value": "ValidPass@123", "verify": "Password field filled"},
            {"action": "click", "target": "id=loginBtn", "verify": "User logged in successfully"},
        ]
    },
    {
        "name": "Login: Invalid Password Error Message",
        "category": "Login & Account Recovery",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
            {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email field filled"},
            {"action": "fill", "target": "id=password", "value": "WrongPassword", "verify": "Wrong password entered"},
            {"action": "click", "target": "id=loginBtn", "verify": "Error: Invalid credentials message appears"},
        ]
    },
    {
        "name": "Login: Account Lockout After Failed Attempts",
        "category": "Login & Account Recovery",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
            {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email filled"},
            {"action": "fill", "target": "id=password", "value": "Wrong1", "verify": "Wrong password entered"},
            {"action": "click", "target": "id=loginBtn", "verify": "Login failed"},
            {"action": "fill", "target": "id=password", "value": "Wrong2", "verify": "Wrong password entered"},
            {"action": "click", "target": "id=loginBtn", "verify": "Login failed"},
            {"action": "fill", "target": "id=password", "value": "Wrong3", "verify": "Login failed"},
            {"action": "click", "target": "id=loginBtn", "verify": "Account locked after 3 failed attempts"},
        ]
    },
    {
        "name": "Login: Password Reset Flow",
        "category": "Login & Account Recovery",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
            {"action": "click", "target": "xpath=//a[text()='Forgot Password?']", "verify": "Password reset page opens"},
            {"action": "fill", "target": "id=email", "value": "user@example.com", "verify": "Email entered"},
            {"action": "click", "target": "id=resetBtn", "verify": "Reset email sent successfully"},
        ]
    },

    # ============ PRODUCT LISTING PAGE (PLP) ============
    {
        "name": "PLP: Sorting Engine - Price Low to High",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
            {"action": "click", "target": "id=sortDropdown", "verify": "Sort dropdown opens"},
            {"action": "click", "target": "xpath=//option[text()='Price: Low to High']", "verify": "Sort option selected"},
            {"action": "verify", "target": "xpath=//div[@class='product-list']", "verify": "Products sorted by price ascending"},
        ]
    },
    {
        "name": "PLP: Multi-Filter Selection - Brand + Price + Color",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
            {"action": "click", "target": "xpath=//label[text()='Samsung']", "verify": "Brand filter selected"},
            {"action": "click", "target": "xpath=//label[text()='$500 - $1000']", "verify": "Price filter selected"},
            {"action": "click", "target": "xpath=//label[text()='Black']", "verify": "Color filter selected"},
            {"action": "verify", "target": "xpath=//div[@class='filtered-results']", "verify": "Results filtered correctly"},
        ]
    },
    {
        "name": "PLP: Grid vs List View Toggle",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads in grid view"},
            {"action": "click", "target": "id=listViewBtn", "verify": "Switch to list view"},
            {"action": "verify", "target": "xpath=//div[@class='product-list-view']", "verify": "List view displays correctly"},
            {"action": "click", "target": "id=gridViewBtn", "verify": "Switch to grid view"},
            {"action": "verify", "target": "xpath=//div[@class='product-grid-view']", "verify": "Grid view displays correctly"},
        ]
    },
    {
        "name": "PLP: Pagination - Navigate Between Pages",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "Page 1 loads with 20 products"},
            {"action": "click", "target": "xpath=//a[text()='2']", "verify": "Navigate to page 2"},
            {"action": "verify", "target": "xpath=//span[text()='Page 2']", "verify": "Page 2 displays correctly"},
            {"action": "click", "target": "xpath=//a[text()='Previous']", "verify": "Navigate back to page 1"},
        ]
    },
    {
        "name": "PLP: Sale/New/Stock Badges Accuracy",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
            {"action": "verify", "target": "xpath=//div[@class='sale-badge' and text()='Sale']", "verify": "Sale badge visible on discounted items"},
            {"action": "verify", "target": "xpath=//div[@class='new-badge' and text()='New']", "verify": "New badge visible on new products"},
            {"action": "verify", "target": "xpath=//div[@class='out-of-stock-badge']", "verify": "Out of Stock badge on unavailable items"},
        ]
    },
    {
        "name": "PLP: Filter State Persistence Across URL Copy",
        "category": "Product Listing Page (PLP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
            {"action": "click", "target": "xpath=//label[text()='Samsung']", "verify": "Brand filter applied"},
            {"action": "click", "target": "xpath=//label[text()='Under $500']", "verify": "Price filter applied"},
            {"action": "execute", "target": "javascript:navigator.clipboard.writeText(window.location.href)", "verify": "URL copied"},
            {"action": "navigate", "target": "javascript:navigator.clipboard.readText()", "verify": "Navigate to copied URL"},
            {"action": "verify", "target": "xpath=//label[@checked and text()='Samsung']", "verify": "Brand filter persisted"},
            {"action": "verify", "target": "xpath=//label[@checked and text()='Under $500']", "verify": "Price filter persisted"},
        ]
    },

    # ============ PRODUCT DISPLAY PAGE (PDP) ============
    {
        "name": "PDP: Variant Switching - Size/Color Updates Price",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/samsung-phone-123", "verify": "PDP loads"},
            {"action": "click", "target": "xpath=//button[@data-size='L']", "verify": "Size L selected"},
            {"action": "verify", "target": "xpath=//span[@class='product-price' and text()='$599']", "verify": "Price updated for size L"},
            {"action": "click", "target": "xpath=//button[@data-color='Blue']", "verify": "Color Blue selected"},
            {"action": "verify", "target": "xpath=//span[@class='product-price' and text()='$699']", "verify": "Price updated for Blue variant"},
        ]
    },
    {
        "name": "PDP: Media Gallery - Image Zoom and Video Playback",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/samsung-phone-123", "verify": "PDP loads"},
            {"action": "click", "target": "xpath=//img[@class='product-thumbnail'][1]", "verify": "First image selected"},
            {"action": "hover", "target": "xpath=//img[@class='product-main-image']", "verify": "Zoom enabled on hover"},
            {"action": "click", "target": "xpath=//button[@class='video-play-btn']", "verify": "Video player opens"},
            {"action": "verify", "target": "xpath=//video[@id='product-video']", "verify": "Video plays smoothly"},
        ]
    },
    {
        "name": "PDP: Low Stock Warning and Out of Stock State",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/low-stock-item", "verify": "PDP loads"},
            {"action": "verify", "target": "xpath=//span[text()='Only 2 items left']", "verify": "Low stock warning displayed"},
            {"action": "navigate", "target": "$BASE_URL/product/out-of-stock-item", "verify": "PDP with out of stock loads"},
            {"action": "verify", "target": "xpath=//button[@disabled and text()='Add to Cart']", "verify": "Add to Cart button disabled"},
        ]
    },
    {
        "name": "PDP: Breadcrumb Navigation",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/samsung-phone-123", "verify": "PDP loads"},
            {"action": "verify", "target": "xpath=//a[text()='Home']", "verify": "Breadcrumb Home link present"},
            {"action": "verify", "target": "xpath=//a[text()='Electronics']", "verify": "Breadcrumb Category link present"},
            {"action": "click", "target": "xpath=//a[text()='Electronics']", "verify": "Navigate to category via breadcrumb"},
        ]
    },
    {
        "name": "PDP: Customer Reviews and Ratings",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/samsung-phone-123", "verify": "PDP loads"},
            {"action": "click", "target": "xpath=//button[@class='write-review-btn']", "verify": "Review form opens"},
            {"action": "click", "target": "xpath=//span[@class='star'][5]", "verify": "5-star rating selected"},
            {"action": "fill", "target": "id=reviewText", "value": "Great product, highly recommended!", "verify": "Review text filled"},
            {"action": "click", "target": "id=submitReviewBtn", "verify": "Review submitted successfully"},
        ]
    },
    {
        "name": "PDP: Dynamic Pricing - Matrix Variant Logic",
        "category": "Product Display Page (PDP)",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/configurable-item", "verify": "PDP with variants loads"},
            {"action": "click", "target": "xpath=//button[@data-variant='premium-base']", "verify": "Premium variant selected"},
            {"action": "verify", "target": "xpath=//span[@class='product-price' and text()='$999']", "verify": "Premium variant price $999"},
            {"action": "click", "target": "xpath=//button[@data-variant='standard-base']", "verify": "Standard variant selected"},
            {"action": "verify", "target": "xpath=//span[@class='product-price' and text()='$599']", "verify": "Standard variant price $599"},
        ]
    },

    # ============ MINI-CART / DRAWER ============
    {
        "name": "Mini-Cart: Flyout Drawer Opens on Add to Cart",
        "category": "Mini-Cart / Drawer",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/samsung-phone-123", "verify": "PDP loads"},
            {"action": "click", "target": "id=addToCartBtn", "verify": "Add to Cart clicked"},
            {"action": "verify", "target": "xpath=//div[@class='mini-cart-drawer']", "verify": "Mini-cart drawer slides out"},
        ]
    },
    {
        "name": "Mini-Cart: Badge Increment and Item Count Update",
        "category": "Mini-Cart / Drawer",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL", "verify": "Home page loads"},
            {"action": "verify", "target": "xpath=//span[@class='cart-badge' and text()='0']", "verify": "Cart badge shows 0"},
            {"action": "navigate", "target": "$BASE_URL/product/item-1", "verify": "Product page loads"},
            {"action": "click", "target": "id=addToCartBtn", "verify": "Add to Cart clicked"},
            {"action": "verify", "target": "xpath=//span[@class='cart-badge' and text()='1']", "verify": "Cart badge increments to 1"},
        ]
    },
    {
        "name": "Mini-Cart: Inline Edit - Modify Quantity",
        "category": "Mini-Cart / Drawer",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL", "verify": "Home page loads"},
            {"action": "click", "target": "id=cartIcon", "verify": "Mini-cart opens"},
            {"action": "fill", "target": "xpath=//input[@class='cart-item-qty']", "value": "3", "verify": "Quantity changed to 3"},
            {"action": "verify", "target": "xpath=//span[@class='cart-total' and text()='$1,797']", "verify": "Cart total updated"},
        ]
    },
    {
        "name": "Mini-Cart: Delete Item from Drawer",
        "category": "Mini-Cart / Drawer",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL", "verify": "Home page loads"},
            {"action": "click", "target": "id=cartIcon", "verify": "Mini-cart opens"},
            {"action": "click", "target": "xpath=//button[@class='delete-item-btn']", "verify": "Delete button clicked"},
            {"action": "verify", "target": "xpath=//div[@class='cart-item']", "verify": "Item removed from cart"},
        ]
    },

    # ============ SECURITY & PENETRATION TESTING ============
    {
        "name": "Security: SQL Injection Prevention in Search",
        "category": "Security & Penetration Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL", "verify": "Home page loads"},
            {"action": "fill", "target": "id=searchBox", "value": "' OR '1'='1", "verify": "SQLi payload entered"},
            {"action": "click", "target": "id=searchBtn", "verify": "Search executed"},
            {"action": "verify", "target": "xpath=//span[text()='No results found']", "verify": "Query parameterized, no injection"},
        ]
    },
    {
        "name": "Security: XSS Prevention in Product Reviews",
        "category": "Security & Penetration Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/product/item-1", "verify": "PDP loads"},
            {"action": "click", "target": "id=writeReviewBtn", "verify": "Review form opens"},
            {"action": "fill", "target": "id=reviewText", "value": "<script>alert('XSS')</script>", "verify": "Script tag entered in review"},
            {"action": "click", "target": "id=submitReviewBtn", "verify": "Review submitted"},
            {"action": "verify", "target": "xpath=//span[text()='&lt;script&gt;alert']", "verify": "Script tag HTML-encoded"},
        ]
    },
    {
        "name": "Security: IDOR - Access Other User's Orders",
        "category": "Security & Penetration Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/user/123456/orders", "verify": "Current user orders load"},
            {"action": "navigate", "target": "$BASE_URL/user/999999/orders", "verify": "Attempt to access another user"},
            {"action": "verify", "target": "xpath=//h1[text()='403 - Unauthorized Access']", "verify": "IDOR prevented, 403 error shown"},
        ]
    },
    {
        "name": "Security: Rate Limiting on Login Attempts",
        "category": "Security & Penetration Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Login page loads"},
            # Simulate 10 rapid login attempts
            {"action": "execute", "target": "javascript:for(let i=0;i<10;i++){fetch('/api/login', {method:'POST'})}"},
            {"action": "wait", "value": 2, "verify": "Wait for rate limiter"},
            {"action": "navigate", "target": "$BASE_URL/login", "verify": "Attempt another login"},
            {"action": "verify", "target": "xpath=//h1[text()='429 - Too Many Requests']", "verify": "Rate limiting triggered"},
        ]
    },

    # ============ PERFORMANCE & LOAD TESTING ============
    {
        "name": "Performance: Largest Contentful Paint (LCP) < 2.5s",
        "category": "Performance & Load Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL", "verify": "Home page navigated"},
            {"action": "execute", "target": "javascript:console.log(performance.getEntriesByName('navigation')[0])", "verify": "LCP measured"},
            {"action": "verify", "target": "javascript:performance.getEntriesByType('largest-contentful-paint')[0].renderTime < 2500", "verify": "LCP < 2500ms"},
        ]
    },
    {
        "name": "Performance: Search Page Load with 3G Network",
        "category": "Performance & Load Testing",
        "steps": [
            {"action": "execute", "target": "javascript:console.log('Simulating 3G connection')", "verify": "3G throttling enabled"},
            {"action": "navigate", "target": "$BASE_URL/search?q=laptop", "verify": "Search page loads on 3G"},
            {"action": "verify", "target": "xpath=//div[@class='search-results']", "verify": "Results load within acceptable time"},
        ]
    },
    {
        "name": "Performance: Infinite Scroll Memory Management",
        "category": "Performance & Load Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/category/electronics", "verify": "PLP loads"},
            {"action": "scroll", "target": "document.body", "value": 5000, "verify": "Scroll down to load more items"},
            {"action": "scroll", "target": "document.body", "value": 10000, "verify": "Continue scrolling"},
            {"action": "execute", "target": "javascript:console.log('Memory: ' + performance.memory.usedJSHeapSize)", "verify": "DOM virtualization working"},
        ]
    },
    {
        "name": "Performance: Debounce on Quantity Input",
        "category": "Performance & Load Testing",
        "steps": [
            {"action": "navigate", "target": "$BASE_URL/cart", "verify": "Cart page loads"},
            {"action": "execute", "target": "javascript:document.querySelectorAll('input.qty-input')[0].value=1; input(new Event('input'))", "verify": "Quantity input 1"},
            {"action": "execute", "target": "javascript:document.querySelectorAll('input.qty-input')[0].value=2; input(new Event('input'))", "verify": "Quantity input 2 immediately after"},
            {"action": "execute", "target": "javascript:document.querySelectorAll('input.qty-input')[0].value=3; input(new Event('input'))", "verify": "Quantity input 3 immediately after"},
            {"action": "wait", "value": 1, "verify": "Wait for debounce"},
            {"action": "verify", "target": "javascript:document.body.innerText", "verify": "Only 1 API request made (debounced)"},
        ]
    },
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
    existing_count = len([t for t in test_cases_table.values() if t.get('projectId') == project_id])
    
    added = []
    for i, tc_template in enumerate(SUPPLEMENTAL_TEST_CASES):
        tcid = make_id()
        tc = {
            "_id": tcid,
            "id": tcid,
            "projectId": project_id,
            "name": tc_template['name'],
            "category": tc_template['category'],
            "steps": tc_template['steps'],
            "source": "manual-supplemental",
            "isRegression": True,
            "sortOrder": existing_count + i,
            "createdAt": now_iso(),
            "updatedAt": now_iso()
        }
        test_cases_table[str(len(test_cases_table))] = tc
        added.append(f"✓ {tc['category']}: {tc['name']}")
    
    db['test_cases'] = test_cases_table
    
    with open(db_path, 'w') as f:
        json.dump(db, f, indent=2)
    
    return added

if __name__ == '__main__':
    added = add_test_cases()
    print(f'Added {len(added)} supplemental test cases:\n')
    for item in added:
        print(item)
    print(f'\nTotal new test cases: {len(added)}')
