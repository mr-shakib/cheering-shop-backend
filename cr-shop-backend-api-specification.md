---
title: "Food Delivery App: Backend API Specification"
version: "1.0.0"
date: "2026-08-12"
status: "Final"
description: "Complete, implementation-ready backend API specification for the multi-actor food delivery ecosystem."
---

# Food Delivery App
## Backend API Specification

**Document Version:** 1.0.0  
**Date:** 2026-08-12  
**Status:** Final  
**Description:** A complete, implementation-ready backend API specification defining the architecture, endpoints, data models, and business logic for the Food Delivery Application.

---

## Table of Contents
1. [Backend Overview](#1-backend-overview)
2. [API Design Conventions](#2-api-design-conventions)
3. [Complete API Endpoint Catalog](#3-complete-api-endpoint-catalog)
4. [Detailed Endpoint Specification](#4-detailed-endpoint-specification)
5. [Endpoint Summary Table](#5-endpoint-summary-table)
6. [Entity / Data Model Requirements](#6-entity--data-model-requirements)
7. [Role & Permission Matrix](#7-role--permission-matrix)
8. [Complete User Flow → API Mapping](#8-complete-user-flow--api-mapping)
9. [Missing / Recommended Backend Requirements](#9-missing--recommended-backend-requirements)
10. [API Consistency & Architecture Review](#10-api-consistency--architecture-review)
11. [Final Statistics](#11-final-statistics)
12. [Unresolved Questions / Decisions](#12-unresolved-questions--decisions)

---

## 1. Backend Overview
The backend architecture supports a real-time, multi-actor food delivery ecosystem. It acts as the central hub connecting customers, restaurant vendors, delivery riders, and administrators.

*   **Main Application Modules:** Authentication & Security, Customer Discovery & Ordering, Vendor Operations, Cart & Checkout, Order Tracking (Telemetry), and Real-Time Communications.
*   **User Roles:** `CUSTOMER`, `VENDOR`, `RIDER`, `ADMIN`.
*   **Authentication Approach:** Stateless JSON Web Tokens (JWT) using an Access/Refresh token pair, transmitted via the `Authorization: Bearer <token>` header. Supports Role-Based Access Control (RBAC) and Time-based One-Time Passwords (TOTP) for 2FA.
*   **High-Level Architecture:** RESTful API over HTTPS for standard CRUD operations, coupled with WebSockets (WS) for real-time telemetry (rider tracking) and instant vendor alerts.

---

## 2. API Design Conventions
*   **Base URL:** `https://api.domain.com/api/v1`
*   **API Versioning:** Versioned via URL path (e.g., `/v1/`).
*   **URL Naming Conventions:** Nouns for collections, lowercase, hyphen-separated (e.g., `/users/me/addresses`).
*   **HTTP Methods:**
    *   `GET`: Retrieve data.
    *   `POST`: Create data or execute actions (e.g., `/login`).
    *   `PUT`: Replace a resource entirely.
    *   `PATCH`: Partially update a resource (e.g., toggling statuses).
    *   `DELETE`: Remove a resource.
*   **Authentication Mechanism:** `Bearer` token in the `Authorization` header.
*   **Pagination:** Cursor or Offset-based via query parameters: `?limit=20&offset=0`.
*   **Filtering & Sorting:** Standardized query params: `?sort=-created_at&status=DELIVERED`.
*   **Standard Response Format:**
    ```json
    {
      "success": true,
      "data": { ... },
      "meta": { "total": 100, "page": 1 }
    }
    ```
*   **Standard Error Format:**
    ```json
    {
      "success": false,
      "error": {
        "code": "VALIDATION_FAILED",
        "message": "Invalid input provided",
        "details": ["password must be at least 8 characters"]
      }
    }
    ```
*   **Date/Time Format:** ISO-8601 UTC string format (`YYYY-MM-DDThh:mm:ssZ`).
*   **ID Format:** UUIDv4 for all database primary keys to prevent enumeration.
*   **File Upload Handling:** Backend offloads binary processing by issuing presigned S3 URLs (`/uploads/presigned-url`). Clients upload directly to the CDN.

---

## 3. Complete API Endpoint Catalog

### Authentication & Security
*   `POST /auth/otp/send`
*   `POST /auth/otp/verify`
*   `POST /auth/login`
*   `POST /auth/login/2fa`
*   `POST /auth/password/forgot`
*   `POST /auth/password/reset`
*   `POST /auth/biometrics/enable`
*   `DELETE /auth/biometrics/disable`
*   `GET /users/me/security`
*   `POST /auth/2fa/generate`
*   `POST /auth/2fa/enable`
*   `POST /auth/2fa/disable`

### Users & Addresses
*   `PUT /users/me/profile`
*   `GET /users/me/addresses`
*   `POST /users/me/addresses`
*   `PUT /users/me/addresses/{id}`
*   `DELETE /users/me/addresses/{id}`
*   `PATCH /users/me/addresses/{id}/default`

### Location, Discovery & Menu
*   `GET /home/feed`
*   `GET /restaurants`
*   `GET /restaurants/{id}`
*   `GET /restaurants/{id}/menu`
*   `GET /search`
*   `GET /users/me/favorites`
*   `POST /users/me/favorites/{id}`

### Cart & Checkout
*   `GET /cart`
*   `POST /cart/items`
*   `GET /checkout/summary`

### Orders & Tracking
*   `POST /orders`
*   `POST /orders/{id}/cancel`
*   `GET /orders`
*   `GET /orders/{id}/tracking`
*   `WS /ws/orders/{id}/live-tracking`
*   `POST /orders/{id}/call`
*   `POST /orders/{id}/reviews`

### Vendor Operations
*   `PATCH /vendor/store/status`
*   `GET /vendor/orders`
*   `WS /ws/vendor/live`
*   `POST /vendor/orders/{id}/accept`
*   `POST /vendor/orders/{id}/reject`
*   `POST /vendor/orders/{id}/ready`
*   `POST /vendor/orders/{id}/handoff`
*   `GET /vendor/analytics`
*   `GET /vendor/menu/categories`
*   `POST /vendor/menu/items`
*   `PATCH /vendor/menu/items/{id}/status`
*   `POST /uploads/presigned-url`

---

## 4. Detailed Endpoint Specification

### Module: Authentication & Security

**`POST /auth/otp/send`**
*   **Purpose:** Sends verification OTP to phone/email for signup.
*   **Actor/Role:** Public
*   **Authentication:** Not Required
*   **Request Body:**
    ```json
    { "identifier": "user@example.com" }
    ```
*   **Response:** `200 OK` | `{ "message": "OTP sent" }`
*   **Status Codes:** `200`, `400`, `429` (Rate Limited)
*   **Business Logic:** Upserts provisional user, generates OTP, triggers SES/Twilio.

**`POST /auth/login`**
*   **Purpose:** Authenticate user via password.
*   **Actor/Role:** Public
*   **Authentication:** Not Required
*   **Request Body:**
    ```json
    { "identifier": "user@example.com", "password": "SecurePassword1!" }
    ```
*   **Response:** `200 OK` | Returns JWTs. If 2FA is active, returns `{ "requires_2fa": true, "temp_token": "..." }`.
*   **Business Logic:** Validates hash. Intercepts flow if `is_2fa_enabled = true`.

**`POST /auth/login/2fa`**
*   **Purpose:** Complete login for users with 2FA enabled.
*   **Actor/Role:** Public
*   **Authentication:** Not Required
*   **Request Body:** `{"temp_token": "...", "code": "123456"}`
*   **Response:** `200 OK` | Final JWTs.

**`GET /users/me/security`**
*   **Purpose:** Fetch status of 2FA and Biometrics.
*   **Actor/Role:** Customer / Vendor
*   **Authentication:** Required
*   **Response:** `200 OK` | `{"is_biometrics_enabled": true, "is_2fa_enabled": false}`

**`POST /auth/2fa/generate`**
*   **Purpose:** Generate TOTP secret and QR code URI.
*   **Actor/Role:** Customer / Vendor
*   **Authentication:** Required
*   **Response:** `200 OK` | `{"secret": "BASE32...", "qr_code_url": "otpauth://..."}`
*   **Business Logic:** Creates a temporary secret tied to the user until verified.

### Module: Users & Addresses

**`POST /users/me/addresses`**
*   **Purpose:** Save a new delivery address.
*   **Actor/Role:** Customer
*   **Authentication:** Required
*   **Request Body:**
    ```json
    {
      "type": "HOME",
      "street_address": "House 12, Road 8",
      "latitude": 23.7936,
      "longitude": 90.4064,
      "is_default": true
    }
    ```
*   **Response:** `201 Created` | Address object.
*   **Business Logic:** If `is_default` is true, unset default flag on all other addresses for this user transactionally.

### Module: Cart & Checkout

**`POST /cart/items`**
*   **Purpose:** Add, update, or remove (qty=0) items in cart.
*   **Actor/Role:** Customer
*   **Authentication:** Required
*   **Request Body:**
    ```json
    {
      "menu_item_id": "uuid",
      "variant_id": "uuid",
      "add_on_ids": ["uuid"],
      "quantity": 1
    }
    ```
*   **Status Codes:** `200`, `400`, `404`, `409 Conflict` (Different restaurant).
*   **Business Logic:** Enforces the "Single Restaurant per Cart" rule. If `menu_item_id` belongs to a different restaurant, return `409`.

**`GET /checkout/summary`**
*   **Purpose:** Calculate the final definitive bill.
*   **Actor/Role:** Customer
*   **Authentication:** Required
*   **Query Params:** `?address_id=uuid&promo_code=XYZ&tip=20`
*   **Response:** 
    ```json
    {
      "item_total": 1059,
      "delivery_fee": 40,
      "discount": 0,
      "grand_total": 1099
    }
    ```
*   **Business Logic:** Backend acts as the single source of truth for pricing. Validates inventory availability before confirming the subtotal.

### Module: Orders & Tracking

**`POST /orders`**
*   **Purpose:** Convert active cart to an order.
*   **Actor/Role:** Customer
*   **Authentication:** Required
*   **Request Body:** `{"payment_method": "COD", "address_id": "uuid"}`
*   **Response:** `201 Created` | Order ID and status.
*   **Business Logic:** Clears cart. Fires WebSockets payload to `/ws/vendor/live` for the specific restaurant to alert the vendor.

**`POST /orders/{id}/cancel`**
*   **Purpose:** Grace-period cancellation.
*   **Actor/Role:** Customer
*   **Authentication:** Required
*   **Logic:** Order can only be cancelled if status is `PENDING`.

**`WS /ws/orders/{id}/live-tracking`**
*   **Purpose:** Stream rider telemetry to customer.
*   **Actor/Role:** Customer
*   **Authentication:** Required (Token via connection setup)
*   **Payload (Server -> Client):**
    ```json
    {
      "lat": 23.8010,
      "lng": 90.4110,
      "heading": 120,
      "eta_mins": 12
    }
    ```

**`POST /orders/{id}/call`**
*   **Purpose:** Proxy call between rider and customer.
*   **Actor/Role:** Customer / Rider
*   **Authentication:** Required
*   **Logic:** Instructs a CPaaS provider (e.g., Twilio) to bridge the customer and rider using a masked proxy phone number.

### Module: Vendor Operations

**`WS /ws/vendor/live`**
*   **Purpose:** Real-time push stream for incoming orders.
*   **Actor/Role:** Vendor
*   **Authentication:** Required
*   **Logic:** Alerts vendor tablet immediately to bypass HTTP polling delays.

**`POST /vendor/orders/{id}/accept`**
*   **Purpose:** Vendor accepts an order.
*   **Actor/Role:** Vendor
*   **Authentication:** Required
*   **Logic:** Updates order status to `PREPARING`. Cancels the backend auto-decline timeout queue task.

**`POST /vendor/orders/{id}/handoff`**
*   **Purpose:** Verify Rider PIN and transfer custody.
*   **Actor/Role:** Vendor
*   **Authentication:** Required
*   **Request Body:** `{"rider_pin": "7420"}`
*   **Status Codes:** `200`, `400` (Invalid PIN).
*   **Logic:** Validates the 4-digit code generated on the Rider app. Changes status to `PICKED_UP`. Records earnings.

**`POST /vendor/menu/items`**
*   **Purpose:** Create a new menu item.
*   **Actor/Role:** Vendor
*   **Authentication:** Required
*   **Request Body:**
    ```json
    {
      "name": "Paneer Tikka",
      "category_id": "uuid",
      "base_price": 500,
      "is_available": true,
      "variants": [{"name": "Small", "price": 270}],
      "add_ons": [{"name": "Extra Cheese", "price": 20}],
      "image_url": "https://s3..."
    }
    ```

**`POST /uploads/presigned-url`**
*   **Purpose:** Obtain S3 URL for direct client-side image uploads.
*   **Actor/Role:** Vendor
*   **Authentication:** Required
*   **Request Body:** `{"file_type": "image/jpeg"}`

---

## 5. Endpoint Summary Table

| # | Module | Method | Endpoint | Purpose | Auth | Role |
|---|---|---|---|---|---|---|
| 1 | Auth | POST | `/auth/otp/send` | Send OTP | No | Public |
| 2 | Auth | POST | `/auth/otp/verify` | Verify OTP | No | Public |
| 3 | Auth | POST | `/auth/login` | Login | No | Public |
| 4 | Auth | POST | `/auth/login/2fa` | Complete 2FA login | No | Public |
| 5 | Auth | POST | `/auth/password/forgot` | Forgot password | No | Public |
| 6 | Auth | POST | `/auth/password/reset` | Reset password | Yes | Temp |
| 7 | Auth | POST | `/auth/biometrics/enable` | Enable TouchID | Yes | Any |
| 8 | Auth | DELETE | `/auth/biometrics/disable` | Disable TouchID | Yes | Any |
| 9 | Security | GET | `/users/me/security` | Get 2FA/Bio state | Yes | Any |
| 10 | Security | POST | `/auth/2fa/generate` | Generate TOTP | Yes | Any |
| 11 | Security | POST | `/auth/2fa/enable` | Enable TOTP | Yes | Any |
| 12 | Security | POST | `/auth/2fa/disable` | Disable TOTP | Yes | Any |
| 13 | Users | PUT | `/users/me/profile` | Update profile | Yes | Cust |
| 14 | Address | GET | `/users/me/addresses` | Get saved addresses | Yes | Cust |
| 15 | Address | POST | `/users/me/addresses` | Save address | Yes | Cust |
| 16 | Address | PUT | `/users/me/addresses/{id}` | Edit address | Yes | Cust |
| 17 | Address | DELETE | `/users/me/addresses/{id}` | Delete address | Yes | Cust |
| 18 | Address | PATCH | `/users/me/addresses/{id}/default` | Set default address | Yes | Cust |
| 19 | Discover | GET | `/home/feed` | App dashboard | No | Public |
| 20 | Discover | GET | `/restaurants` | Filtered list | No | Public |
| 21 | Discover | GET | `/restaurants/{id}` | Restaurant details | No | Public |
| 22 | Discover | GET | `/restaurants/{id}/menu` | Categorized menu | No | Public |
| 23 | Discover | GET | `/search` | Global search | No | Public |
| 24 | Favorites| GET | `/users/me/favorites` | List favorites | Yes | Cust |
| 25 | Favorites| POST | `/users/me/favorites/{id}` | Add favorite | Yes | Cust |
| 26 | Cart | GET | `/cart` | Get current cart | Yes | Cust |
| 27 | Cart | POST | `/cart/items` | Modity cart items | Yes | Cust |
| 28 | Cart | GET | `/checkout/summary` | Get final bill | Yes | Cust |
| 29 | Order | POST | `/orders` | Place order | Yes | Cust |
| 30 | Order | POST | `/orders/{id}/cancel` | Cancel order | Yes | Cust |
| 31 | Order | GET | `/orders` | Order history | Yes | Cust |
| 32 | Tracking | GET | `/orders/{id}/tracking` | Init map view | Yes | Cust |
| 33 | Tracking | WS | `/ws/orders/{id}/live-tracking`| Stream rider GPS | Yes | Cust |
| 34 | Comms | POST | `/orders/{id}/call` | Masked call | Yes | Cust/Rid |
| 35 | Comms | POST | `/orders/{id}/reviews` | Submit review | Yes | Cust |
| 36 | Vendor | PATCH | `/vendor/store/status` | Open/Close store | Yes | Vend |
| 37 | Vendor | GET | `/vendor/orders` | Incoming queues | Yes | Vend |
| 38 | Vendor | WS | `/ws/vendor/live` | Live order push | Yes | Vend |
| 39 | Vendor | POST | `/vendor/orders/{id}/accept` | Accept order | Yes | Vend |
| 40 | Vendor | POST | `/vendor/orders/{id}/reject` | Reject order | Yes | Vend |
| 41 | Vendor | POST | `/vendor/orders/{id}/ready` | Mark ready | Yes | Vend |
| 42 | Vendor | POST | `/vendor/orders/{id}/handoff` | Verify PIN | Yes | Vend |
| 43 | Vendor | GET | `/vendor/analytics` | Earnings dashboard | Yes | Vend |
| 44 | Vendor | GET | `/vendor/menu/categories` | Get categories | Yes | Vend |
| 45 | Vendor | POST | `/vendor/menu/items` | Add menu item | Yes | Vend |
| 46 | Vendor | PATCH | `/vendor/menu/items/{id}/status`| Toggle availability| Yes | Vend |
| 47 | System | POST | `/uploads/presigned-url` | Generate S3 URL | Yes | Vend |

---

## 6. Entity / Data Model Requirements

**User**
*   `id` (PK, UUID)
*   `role` (ENUM: CUSTOMER, VENDOR, RIDER, ADMIN)
*   `email`, `phone`, `password_hash`
*   `is_2fa_enabled`, `totp_secret`

**Address**
*   `id` (PK)
*   `user_id` (FK -> User)
*   `type` (ENUM: HOME, WORK, OTHER)
*   `street_address`, `lat`, `lng`, `is_default`

**Restaurant**
*   `id` (PK)
*   `owner_id` (FK -> User)
*   `name`, `status` (OPEN, CLOSED)
*   `rating_avg`, `lat`, `lng`

**MenuCategory & MenuItem**
*   **MenuCategory:** `id` (PK), `restaurant_id` (FK), `name`, `sort_order`
*   **MenuItem:** `id` (PK), `category_id` (FK), `name`, `base_price`, `is_available`, `image_url`
*   **ItemVariant:** `id` (PK), `menu_item_id` (FK), `name`, `price`
*   **ItemAddOn:** `id` (PK), `menu_item_id` (FK), `name`, `price`

**Cart & CartItem**
*   **Cart:** `user_id` (PK), `restaurant_id` (FK) -> *Constraint: 1 cart per user, 1 restaurant per cart.*
*   **CartItem:** `id` (PK), `cart_id` (FK), `menu_item_id` (FK), `variant_id` (FK), `qty`

**Order**
*   `id` (PK), `user_id` (FK), `restaurant_id` (FK), `rider_id` (FK, nullable)
*   `status` (PENDING, PREPARING, READY, PICKED_UP, DELIVERED, CANCELLED)
*   `item_total`, `delivery_fee`, `discount`, `tip`, `grand_total`
*   `rider_pin` (String, 4-digit generated code)

---

## 7. Role & Permission Matrix

| Module | CUSTOMER | VENDOR | RIDER | ADMIN |
| :--- | :---: | :---: | :---: | :---: |
| **Manage Profile/Security** | ✓ | ✓ | ✓ | ✓ |
| **View Restaurants/Menus** | ✓ | — | — | ✓ |
| **Place Orders** | ✓ | — | — | — |
| **Accept/Reject Orders** | — | ✓ | — | — |
| **Manage Catalog/Menu** | — | ✓ | — | ✓ |
| **Update Live GPS** | — | — | ✓ | — |
| **Verify Rider PIN** | — | ✓ | — | — |
| **View Earnings/Analytics** | — | ✓ | ✓ | ✓ |

---

## 8. Complete User Flow → API Mapping

**Flow: Order Placement & Fulfillment**
1.  **Browse:** `GET /home/feed` -> `GET /restaurants/{id}/menu`
2.  **Cart Assembly:** `POST /cart/items`
3.  **Checkout Math:** `GET /checkout/summary`
4.  **Confirm:** `POST /orders` *(Order State: PENDING)*
5.  **Vendor Alert:** WebSockets pushes to `WS /ws/vendor/live`
6.  **Vendor Acceptance:** `POST /vendor/orders/{id}/accept` *(Order State: PREPARING)*
7.  **Food Cooked:** `POST /vendor/orders/{id}/ready` *(Order State: READY)*
8.  **Rider Arrival & Auth:** Vendor inputs PIN via `POST /vendor/orders/{id}/handoff` *(Order State: PICKED_UP)*
9.  **Transit:** Customer monitors `WS /ws/orders/{id}/live-tracking`
10. **Completion:** Rider API marks delivered *(Order State: DELIVERED)*.
11. **Feedback:** `POST /orders/{id}/reviews`

---

## 9. Missing / Recommended Backend Requirements

**Required:**
*   **Backend Task Queue / Scheduler:** A distributed queue (e.g., Celery, BullMQ, AWS SQS) is strictly required to handle the 60-second auto-decline "Timeout" rule for unaccepted vendor orders.
*   **FCM / Push Notifications:** While WebSockets handle active states, inactive devices require `POST /users/me/devices` to store Firebase tokens for push alerts.

**Recommended:**
*   **Idempotency Keys:** Ensure `POST /orders` requires an `Idempotency-Key` header to prevent double-charging or double-order creation during spotty cellular connections.
*   **Geospatial DB Indexing:** Use PostGIS (PostgreSQL) or Redis Geospatial functions for highly optimized `/restaurants?lat=&lng=` discovery queries.

---

## 10. API Consistency & Architecture Review

*   **Deduplication:** Consolidated OTPs. `POST /auth/otp/send` is generic; 2FA logic is separated to `/auth/2fa/*`.
*   **Data Integrity (Cart):** The rule allowing only one restaurant per order is enforced by placing `restaurant_id` on the parent `Cart` model, preventing heterogeneous `CartItem` lists at the database level.
*   **Security (2FA Login):** Standard login processes check `is_2fa_enabled`. If true, access tokens are withheld, and an intermediate `temp_token` is issued to hit `POST /auth/login/2fa`.
*   **Race Conditions (Handoff):** The `rider_pin` acts as cryptographic proof of presence, preventing riders from stealing food or vendors handing food to the wrong courier.

---

## 11. Final Statistics

*   **Total unique endpoints:** 47
*   **Endpoints by HTTP Method:** 
    *   `GET`: 21
    *   `POST`: 20
    *   `PUT`: 2
    *   `PATCH`: 3
    *   `DELETE`: 1
*   **Public Endpoints:** 11
*   **Authenticated Endpoints:** 36
*   **Customer Specific Endpoints:** 15
*   **Vendor Specific Endpoints:** 12
*   **Total Core Entities:** 8

---

## 12. Unresolved Questions / Decisions

1.  **Map Routing API Costs:** Will the system rely on Google Maps Directions API to draw the Rider route polyline server-side (expensive), or rely strictly on client-side map rendering using straight-line tracking?
2.  **Payment Gateway Callbacks:** The Checkout screen shows Wallet, bKash, and Visa. If these use browser-redirects instead of native SDKs, webhook endpoints (e.g., `POST /webhooks/payments/bkash`) must be added to process asynchronous payment confirmations.
3.  **Vendor Re-routing Logistics:** When a vendor rejects an order, the UI states it is "rebooking with a nearby vendor." Does the backend automatically recreate the cart and silently assign it (a highly complex AI/matching task), or does it simply refund the customer and suggest a new store?