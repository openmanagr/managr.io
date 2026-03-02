# OpenManagr 🤖📊

**Open-source AI accounting agent for Zimbabwe**

OpenManagr automates monthly accounting closes, reconciles transactions, applies IAS 29 inflation adjustments, and generates intelligent reports with commentary—all running on a Raspberry Pi.

## ✨ Features

- **Automated Monthly Close** - Runs on the 3rd of each month
- **ERP Integration** - Sage, Xero, QuickBooks via Apideck
- **IFRS Assistant** - Ask questions about accounting standards
- **IAS 29 Engine** - Zimbabwe-specific inflation accounting
- **Intelligent Reconciliation** - Finds discrepancies automatically
- **Beautiful Reports** - Excel + PDF with charts and narrative
- **Email Delivery** - Sends to accountant for review
- **Runs on Raspberry Pi** - $155 one-time cost, no cloud dependency

## 🏗️ Architecture

![Architecture](docs/images/architecture.png)

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/openmanagr.git
cd openmanagr

# Copy environment variables
cp .env.example .env

# Start with Docker
docker-compose up -d

# Access the dashboard
open http://localhost:3000
```
