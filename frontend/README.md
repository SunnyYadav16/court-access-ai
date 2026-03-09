# CourtAccess AI — Frontend

UI prototype for the CourtAccess AI MLOps project. Built with Vite, React, TypeScript, Tailwind CSS v4, and shadcn/ui.

## Tech Stack

- Vite 7 + React 19 + TypeScript
- Tailwind CSS v4
- shadcn/ui
- pnpm

## Getting Started

```bash
pnpm install
pnpm run dev
```

Open http://localhost:5173

## Build for Production

```bash
pnpm run build
```

## Environment Variables

Copy `.env.example` to `.env` and fill in values before backend integration:

```bash
cp .env.example .env
```

## Project Structure

```
src/
├── components/
│   ├── shared/
│   │   ├── ScreenLabel.tsx       Fixed label showing current screen name
│   │   ├── ScreenNavigator.tsx   Dev sidebar for navigating all 22 screens
│   │   └── TopBar.tsx            Authenticated top navigation bar
│   └── ui/                       shadcn/ui components
│       ├── badge.tsx
│       ├── button.tsx
│       ├── card.tsx
│       ├── input.tsx
│       ├── select.tsx
│       └── separator.tsx
├── screens/
│   ├── LandingScreen.tsx         Public landing page (default, no auth required)
│   ├── auth/
│   │   ├── LoginScreen.tsx
│   │   ├── SignupScreen.tsx
│   │   ├── ForgotScreen.tsx
│   │   ├── ResetScreen.tsx
│   │   ├── VerifyEmailScreen.tsx
│   │   └── MFAScreen.tsx
│   ├── home/
│   │   ├── HomePublic.tsx        Home for public users
│   │   ├── HomeOfficial.tsx      Home for court officials
│   │   ├── HomeInterpreter.tsx   Home for interpreters
│   │   └── HomeAdmin.tsx         Home for admins
│   ├── realtime/
│   │   ├── RealtimeSetup.tsx     Session configuration
│   │   └── RealtimeSession.tsx   Live interpretation session
│   ├── documents/
│   │   ├── DocUpload.tsx         PDF upload screen
│   │   ├── DocProcessing.tsx     Pipeline processing status
│   │   └── DocResults.tsx        Translation download
│   ├── forms/
│   │   ├── FormsLibrary.tsx      Browse pre-translated court forms
│   │   └── FormDetail.tsx        Individual form download
│   └── admin/
│       ├── AdminDashboard.tsx    System monitoring and model health
│       ├── AdminUsers.tsx        User management
│       ├── AdminForms.tsx        Form scraper management
│       └── InterpreterReview.tsx Translation review queue
├── lib/
│   ├── constants.ts              Design tokens and screen IDs
│   └── utils.ts                  shadcn utility (cn function)
└── App.tsx                       Root component and screen router
```

## User Flow

```
Landing Page (public)
    └── Sign In to Use Services
            └── Login → MFA
                    ├── Public User       → HomePublic
                    ├── Court Official    → HomeOfficial
                    ├── Interpreter       → HomeInterpreter
                    └── Admin             → HomeAdmin
```

## Notes

- All data is currently mocked — backend integration pending
- Role-based routing is simulated — will be driven by auth token claims post-integration
- The left sidebar (ScreenNavigator) is a development tool for reviewing all screens and will be removed before production
- `.env` variables are not required to run the prototype — all auth and data is mocked. They will be needed once the backend and real OAuth providers are integrated