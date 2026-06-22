# CashPilot AI 💰🤖

An AI-powered CFO assistant designed to help small businesses make smarter financial decisions through cash flow analysis, payment prioritization, scenario simulation, and AI-driven financial recommendations.

---

## Problem Statement

Small businesses often make financial decisions based only on their current bank balance without considering future obligations, cash runway, pending receivables, or payment priorities.

This can result in:

* Cash shortages
* Missed vendor payments
* Poor financial planning
* Reduced business stability

CashPilot AI addresses this problem by providing intelligent financial insights, forecasting, and AI-powered decision support.

---

## Features

### 📊 Dashboard

Provides a real-time overview of business finances including:

* Current Cash Balance
* Total Payables
* Total Receivables
* Upcoming Bills
* Cash Runway
* Invoice Count

---

### 📄 Invoice Hub

Centralized invoice management system that allows businesses to:

* Track invoices
* Manage receivables
* Manage payables
* Organize financial records

Each invoice is automatically analyzed and assigned an AI Priority Score.

---

### 🎯 AI Payment Prioritization

Invoices are ranked using a weighted scoring model based on:

* Due Date Urgency
* Invoice Amount
* Business Category Importance

Priority Levels:

* Critical
* High
* Medium
* Low

This helps businesses decide which payments should be handled first.

---

### 📈 Cash Runway Calculator

Calculates how long a business can sustain operations based on:

Current Cash Balance

and

Monthly Burn Rate

Formula:

Cash Runway = (Current Balance / Monthly Burn Rate) × 30

---

### 🔮 Scenario Simulator

Allows businesses to simulate future expenses before committing to them.

The system instantly calculates:

* Projected Balance
* Projected Cash Runway
* Financial Risk Level
* AI CFO Recommendation

This helps users evaluate spending decisions before they occur.

---

### 🤖 AI CFO Recommendation Engine

Powered by Google Gemini.

The AI analyzes:

* Cash Position
* Payables
* Receivables
* Runway
* Scenario Impact

And generates:

* Risk Level
* Recommendation
* Key Concern
* Suggested Action

Providing CFO-level financial guidance in seconds.

---

### 💬 AI CFO Chat Assistant

A specialized financial chatbot that only answers questions related to:

* Cash Flow
* Runway
* Payables
* Receivables
* Vendor Payments
* Business Finance

The chatbot uses real business data to provide contextual financial recommendations.

---

### 📊 Analytics Dashboard

Advanced financial analytics including:

* Net Cash Flow Analysis
* Liquidity Monitoring
* Expense Distribution
* Financial Trends
* Runway Forecasting

Helping businesses identify risks and opportunities.

---

### 🤝 Vendor Negotiation Assistant

Uses AI to generate vendor communication recommendations and negotiation strategies to help businesses:

* Preserve liquidity
* Request payment extensions
* Maintain vendor relationships

---

## Tech Stack

### Frontend

* HTML
* JavaScript
* Tailwind CSS

### Backend

* FastAPI
* Python

### Database

* SQLite

### AI Layer

* Google Gemini

---

## System Architecture

User

↓

Frontend (HTML + JavaScript + Tailwind CSS)

↓

FastAPI Backend

├── Dashboard Service

├── Invoice Management Service

├── Payment Prioritization Engine

├── Scenario Simulation Engine

├── Vendor Negotiation Service

├── AI CFO Recommendation Service

└── CFO Chat Service

↓

SQLite Database

↓

Google Gemini AI

---

## Why CashPilot AI?

### Modular Architecture

Each feature operates independently:

* Dashboard
* Invoice Hub
* Analytics
* Scenario Simulator
* AI Recommendations
* CFO Chat

This allows new features to be added without affecting existing functionality.

### Scalable Architecture

The platform is built using API-driven services.

Future integrations can include:

* ERP Systems
* Banking APIs
* Accounting Software
* Payment Gateways
* PostgreSQL
* Cloud Infrastructure

without major architectural changes.

---

## Future Scope

* Real-Time Banking Integration
* Automated Invoice Extraction
* Predictive Cash Forecasting
* Autonomous Payment Planning
* Advanced Vendor Negotiation Workflows
* Multi-Business Support
* Cloud Deployment

---

## Project Impact

CashPilot AI enables businesses to move from reactive financial management to proactive financial planning.

Instead of waiting for cash shortages to occur, businesses can:

* Predict financial risks
* Optimize payments
* Improve liquidity
* Extend runway
* Make informed decisions

with the support of AI-powered financial intelligence.

---

## Team

Built as a hackathon project to demonstrate how AI can transform financial decision-making for small businesses.

### CashPilot AI

Your Intelligent CFO Assistant 🚀
