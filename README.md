# UDOM e-Store — University of Dodoma Digital Marketplace

A centralized digital marketplace for the University of Dodoma (UDOM), designed to store and distribute software, applications, and PaaS solutions — similar to Google Play Store / Apple App Store.

---

## Overview

The UDOM e-Store enables the UDOM community to showcase, distribute, and monetize software in a controlled and manageable ecosystem.

### User Roles

| Role | Access |
|------|--------|
| **Admin** | Full system access — manage users, apps, subscriptions, payments, source code |
| **Internal** (students/lecturers) | Free access to all campus applications |
| **External** | View public listings; must subscribe and pay for full access |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, Django 4.2, Django REST Framework |
| Frontend | JavaScript, React 18, React Router v6 |
| Database | PostgreSQL 15 |
| Auth | JWT (djangorestframework-simplejwt) |
| Containerization | Docker, Docker Compose |
| Web Server | Nginx |

---

## Project Structure

```
udom-estore/
├── backend/                  # Django REST API
│   ├── accounts/             # User management & authentication
│   ├── marketplace/          # App listings, categories, reviews
│   ├── subscriptions/        # Subscription plans & management
│   ├── payments/             # Payment processing
│   └── udom_backend/         # Django project settings
├── frontend/                 # React SPA
│   └── src/
│       ├── api/              # Axios API client
│       ├── components/       # Reusable UI components
│       ├── context/          # Auth context
│       └── pages/            # Route-level page components
├── nginx/                    # Reverse proxy configuration
└── docker-compose.yml        # Container orchestration
```

---

## Quick Start

### Prerequisites
- Docker & Docker Compose

### 1. Clone & Configure
```bash
git clone <repository-url>
cd Dropship-repository
cp .env.example .env
# Edit .env with your settings
```

### 2. Start All Services
```bash
docker-compose up --build
```

### 3. Create Admin User
```bash
docker-compose exec backend python manage.py createsuperuser
```

### 4. Access the Platform
| Service | URL |
|---------|-----|
| Frontend (React) | http://localhost:3000 |
| Backend API | http://localhost:8000/api |
| API Docs (Swagger) | http://localhost:8000/api/docs |
| Django Admin | http://localhost:8000/admin |

---

## API Endpoints

### Authentication
```
POST   /api/auth/register/           Register new user
POST   /api/auth/login/              Login (returns JWT tokens)
POST   /api/auth/logout/             Logout
GET    /api/auth/profile/            Get current user profile
PUT    /api/auth/profile/            Update profile
POST   /api/auth/change-password/    Change password
POST   /api/auth/token/refresh/      Refresh JWT token
```

### Marketplace
```
GET    /api/marketplace/apps/            List all apps (filterable)
POST   /api/marketplace/apps/           Submit new app
GET    /api/marketplace/apps/{id}/      App details
PUT    /api/marketplace/apps/{id}/      Update app (owner/admin)
GET    /api/marketplace/apps/featured/  Featured apps
POST   /api/marketplace/apps/{id}/download/ Download app
GET    /api/marketplace/categories/     List categories
GET    /api/marketplace/reviews/        App reviews
POST   /api/marketplace/reviews/        Submit review
```

### Subscriptions
```
GET    /api/subscriptions/plans/       List subscription plans
POST   /api/subscriptions/subscribe/   Subscribe to a plan
GET    /api/subscriptions/my/          My active subscriptions
```

### Payments
```
POST   /api/payments/initiate/         Initiate payment
GET    /api/payments/history/          Payment history
POST   /api/payments/webhook/          Payment webhook
```

---

## Development

### Backend Only
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

### Frontend Only
```bash
cd frontend
npm install
npm start
```

---

## Features

- **App Store UI** — Play Store/App Store-inspired interface
- **Role-Based Access Control** — Admin, Internal, External user tiers
- **App Submissions** — Internal users and admins can publish applications
- **Admin Review Workflow** — Apps go through pending → approved/rejected
- **Subscription System** — Monthly, quarterly, and annual plans for external users
- **Payment Integration** — Card, Mobile Money, and Bank Transfer support
- **Search & Discovery** — Full-text search, category filters, featured banners
- **Reviews & Ratings** — 5-star rating system with verified purchase badges
- **Download Tracking** — Per-user and per-app download statistics
- **Responsive Design** — Works on desktop, tablet, and mobile

---

## License

University of Dodoma — Internal Use
