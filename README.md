# JanSetu — AI-Powered Citizen Grievance Management System

A production-ready, full-stack web application for citizens to raise grievances and
for government validators and officials to review, verify and resolve them — with
**Admin Approval** and **Face Authentication** securing staff accounts, and Google
Gemini AI doing the heavy lifting (transcription, PII removal, summaries, category
validation and urgency scoring).

| Layer      | Technology                                                        |
| ---------- | ----------------------------------------------------------------- |
| Frontend   | HTML, CSS, JavaScript (no frameworks), MediaRecorder, MediaDevices, Geolocation API, face-api.js (liveness) |
| Backend    | Python · Django · Django REST Framework                           |
| Database   | MongoDB (MongoEngine) — Atlas or local                            |
| Auth       | JWT (access + refresh + face-challenge tokens), bcrypt password hashing |
| Face Auth  | OpenCV (Haar cascade + LBP embedding) · optional DeepFace / face_recognition · Fernet-encrypted embeddings |
| AI         | Google Gemini API with automatic realistic mock fallback          |
| UI         | Responsive, dark mode, 5-language switcher (English, हिंदी, मराठी, ಕನ್ನಡ, বাংলা) |

---

## ✨ Features

### Roles
1. **Citizen** — registers instantly with name/email/username/password and logs in directly.
2. **Validator** — applies for an account; a Super Admin must approve, then face authentication.
3. **Official** — exactly the same flow as a Validator.
4. **Super Admin** — approves/rejects applications, manages users, complaints, reports and audit logs.

### Admin Approval Workflow
- Validators & Officials fill an **application form** (department, employee ID, office,
  Government ID upload, Employee ID card, profile photo) and **capture 5–10 face images**.
- The account starts as **Pending Approval** and **cannot log in** until approved.
- The Super Admin reviews each application (documents, face-registration status, date)
  and **approves** or **rejects** (with a mandatory reason).
- On approval the applicant is notified by **email + in-app notification** and can log in.
- On rejection the applicant sees the **reason** and cannot log in.

### Face Authentication (Validators & Officials)
- **Login is two-step**: password, then a live webcam **liveness + face check**.
- Liveness challenges: **blink detection** and **head-turn** (face-api.js landmarks), with
  a server-side liveness gate (frames, blinks, head-turn, score).
- Face embeddings are compared against the stored **encrypted** embedding with cosine
  similarity — match **≥ 90%** required (configurable).
- Only the **encrypted embedding** is stored; raw face images are never persisted.

### Citizen
- Registration & login (JWT secured, bcrypt hashing)
- Dashboard with analytics (total / pending / verified / resolved)
- Submit complaints with:
  - **Voice recording** via the browser microphone (`MediaRecorder`)
  - **Photo capture or upload** via the camera (`MediaDevices`)
  - **Auto GPS location** with reverse geocoding (`Geolocation API` + Nominatim)
  - Category + description
- AI processes every complaint: transcribes audio, removes PII, generates a summary,
  validates the category and assigns an urgency score (1–10)
- Unique **Complaint ID** (e.g. `JST-4K9XM2P7`), **6-digit PIN** and **SHA-256 hash**

### Validator & Official (after approval)
- Validator: review pending complaints, verify/reject with remarks.
- Official: view verified complaints, add remarks, mark **Resolved**.

### Super Admin Panel
- Dashboard statistics (citizens, pending/approved validators & officials, rejected
  applications, resolved/pending complaints)
- **Applications** — list/detail/approve/reject (tabs + role filter + search)
- **Users** — deactivate/activate, **reset face**, **reset password**
- **Complaint registry** — every complaint with full timeline
- **Reports** — status/category/role breakdowns + 14-day signup trend
- **Audit log** and **login history** (password + face attempts)

### Notifications
Email + in-app dashboard notifications on: application submitted, approved, rejected,
face reset, password changed. (Console email backend when SMTP is unconfigured.)

---

## 📁 Project structure

```
jansetu/                     # Django project (settings, urls, wsgi/asgi)
apps/
├── core/                    # utils, pagination, exception handler, seed_data command
├── authentication/          # User/Application/Notification/LoginHistory/AuditLog models,
│                            # face_auth service, JWT + face-challenge tokens, auth APIs
├── admin_panel/             # Super Admin APIs (applications, users, complaints, reports, audit)
├── complaints/              # Complaint model + timeline, workflow APIs, analytics
└── ai_services/             # Gemini client + mock AI pipeline
templates/                   # Landing, auth, dashboards, admin pages, details, profile, settings
static/
├── css/                     # style.css (design system) + features.css (admin/face)
├── js/                      # api, ui, i18n (5 languages), theme, common, face, auth, admin-*
└── icons.svg                # Inline SVG icon sprite
```

---

## 🚀 Getting started

### 1. Prerequisites
- Python 3.10+ (tested with 3.13)
- MongoDB — **Atlas** (recommended) or local `mongod`
- (Optional) A [Google Gemini API key](https://aistudio.google.com/apikey)

### 2. Create a virtual environment & install

```bash
cd JanSetu
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` installs `opencv-python-headless` for face detection/embeddings and
`cryptography` for Fernet encryption of embeddings. For higher-accuracy embeddings you
may optionally install `deepface` (pulls in TensorFlow); when absent the pipeline uses
the OpenCV local-binary-pattern embedding, and finally a documented mock as a fallback.

### 3. Configure environment

```bash
cp .env.example .env
# edit .env:  MONGODB_URI, GEMINI_API_KEY (optional), EMAIL_* (optional), FACE_* settings
```

### 4. Seed demo data

```bash
python manage.py seed_data
```

| Role        | Email                    | Password       | Login                        |
| ----------- | ------------------------ | -------------- | ---------------------------- |
| Citizen     | `citizen@example.com`    | `Citizen@123`  | password only                |
| Validator   | `validator@example.com`  | `Validator@123`| password + **face auth**     |
| Official    | `official@example.com`   | `Official@123`| password + **face auth**     |
| Super Admin | `admin@example.com`      | `Admin@123`    | password only                |

> `FACE_DEMO_MODE=True` is the default so demo staff accounts can complete the face step
> with any webcam. **Set `FACE_DEMO_MODE=False` in production** for strict biometric matching.

### 5. Run the server

```bash
python manage.py runserver
```

Open **http://127.0.0.1:8000/**.

### Running without MongoDB (in-memory, for testing)

```bash
pip install -r requirements-dev.txt
MONGODB_URI=mongomock://localhost/jansetu_dev python scripts/run_dev_server.py
```

### Running the test suite & smoke tests

```bash
MONGODB_URI=mongomock://localhost/jansetu_test python manage.py test
MONGODB_URI=mongomock://localhost/jansetu_dev python scripts/e2e_smoke.py   # full API workflow
MONGODB_URI=mongomock://localhost/jansetu_dev python scripts/check_fixes.py # targeted checks
```

---

## 🔌 API reference

All endpoints return JSON. Authenticate with `Authorization: Bearer <access_token>`.

### Authentication — `/api/auth/`
| Method | Path                      | Role      | Description                        |
| ------ | ------------------------- | --------- | ---------------------------------- |
| POST   | `register/`               | public    | Citizen (instant) OR Validator/Official **application** |
| POST   | `login/`                  | public    | identifier + password → tokens or **face challenge** |
| POST   | `refresh/`                | public    | Refresh token → new token pair     |
| GET    | `me/`                     | any       | Current user profile               |
| PUT    | `profile/`                | any       | Update full_name / phone / office fields |
| POST   | `change-password/`        | any       | Change password                    |
| POST   | `register-face/`          | staff     | Capture 5–10 frames → encrypted embedding |
| POST   | `verify-face/`            | staff     | Live frame + liveness → tokens     |
| GET    | `notifications/`          | any       | In-app notifications + unread count |
| POST   | `notifications/read/`     | any       | Mark notification(s) read          |

### Super Admin — `/api/admin/`
| Method | Path                                   | Description                        |
| ------ | -------------------------------------- | ---------------------------------- |
| GET    | `dashboard/`                           | Platform statistics                |
| GET    | `applications/`                        | Applications (status/role/search)  |
| GET    | `applications/<id>/`                   | Application detail                 |
| PATCH  | `applications/<id>/approve/`           | Approve application                |
| PATCH  | `applications/<id>/reject/`            | Reject application (remarks required) |
| GET    | `users/`                               | Users (role/status/search)         |
| PATCH  | `users/<id>/deactivate/` · `activate/` | Suspend / reactivate               |
| PATCH  | `users/<id>/reset-face/`               | Reset face authentication          |
| PATCH  | `users/<id>/reset-password/`           | Admin password reset               |
| GET    | `complaints/` · `complaints/<id>/`     | Complaint registry + detail        |
| GET    | `reports/`                             | Aggregates & trends                |
| GET    | `audit-logs/`                          | Audit trail                        |
| GET    | `login-history/`                       | Login attempts (password + face)   |

Flat spec-style aliases are also mounted: `PATCH /api/admin/applications/approve/`,
`/api/admin/applications/reject/`, `/api/admin/reset-face/`, `/api/admin/deactivate-user/`
(id passed in the request body).

### Complaints — `/api/`
| Method | Path                              | Role      | Description                         |
| ------ | --------------------------------- | --------- | ----------------------------------- |
| GET    | `complaints/`                     | any       | Role-scoped list (search/filter/sort/paginate) |
| POST   | `complaints/`                     | citizen   | Submit complaint (multipart)        |
| GET    | `complaints/<id>/`                | owner/any | Full details + timeline + hash      |
| POST   | `complaints/<id>/validate/`       | validator | `{action: verify\|reject, remarks}` |
| POST   | `complaints/<id>/resolve/`        | official  | `{remarks}` — marks resolved        |
| GET    | `analytics/`                      | any       | Role-aware dashboard statistics     |

---

## 🧠 How face authentication works

```
Registration
  webcam 5–10 frames ──► OpenCV face detection ──► embedding (DeepFace / OpenCV LBP / mock)
        ──► L2-normalise ──► Fernet-encrypt ──► stored on the User document (never raw)

Login (staff)
  password ──► account-status gate (PENDING/REJECTED blocked) ──► face-challenge JWT
  live webcam ──► liveness (blinks + head-turn + frame burst) ──► server-side liveness gate
        ──► detect face ──► embedding ──► decrypt stored ──► cosine similarity ≥ 90% ──► JWT pair
```

---

## 🛡️ Security notes
- Passwords hashed with **bcrypt (12 rounds)**; **JWT** access (24h) + refresh (7d) tokens.
- **Face embeddings are stored encrypted (Fernet)** — raw images never persisted.
- Staff accounts are gated by `account_status`; pending/rejected/suspended accounts cannot log in.
- **Liveness + anti-spoofing**: blink detection, head-turn challenges, minimum frame count and
  a server-side liveness score threshold.
- **Brute-force protection**: accounts lock after `MAX_LOGIN_ATTEMPTS` failed logins.
- Role-based permissions (`IsCitizen`, `IsValidator`, `IsOfficial`, `IsSuperAdmin`).
- Complaints are role-scoped; the complaint PIN is returned **only to the owning citizen**.
- Uploads are size-, extension- and magic-byte-checked.
- A central exception handler maps MongoEngine errors to clean JSON.
- Every admin action writes an **audit log**; every login writes a **login-history** row.

> For production: set a strong `DJANGO_SECRET_KEY`/`FACE_ENCRYPTION_KEY`, `DEBUG=False`,
> `FACE_DEMO_MODE=False`, restrict `ALLOWED_HOSTS`, configure SMTP email, serve static
> files via a CDN/web server, and move uploads to object storage (S3 etc.).

---

## 📄 License
MIT — free to use, modify and distribute.
