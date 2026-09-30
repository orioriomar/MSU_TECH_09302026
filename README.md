# HSIBOTB2026_Montclair
# ProofLayer

### Trustworthy AI Product Discovery for Small Businesses

**Montclair State University**  
**2026 HSI Battle of the Brains — Austin, Texas**

---

## Overview

Consumers are increasingly beginning their shopping journeys with AI
assistants instead of traditional search engines. While this makes product
discovery faster, it creates a new challenge for businesses: a company may
never reach a potential customer if an AI assistant fails to recommend its
products or provides incorrect information about them.

**ProofLayer** is a web-based platform designed to help small businesses
monitor and improve how they are represented in AI-assisted shopping.

ProofLayer focuses on three core areas:

- **Visibility** — Is the business appearing in relevant AI recommendations?
- **Accuracy** — Is the AI providing correct information about the business
  and its products?
- **Governance** — When incorrect information is detected, how can the issue
  be reviewed and addressed responsibly?

The platform combines AI-powered testing, verified business data,
discrepancy detection, and a human-reviewed ticketing system in one
centralized dashboard.

---

## The Problem

AI assistants are becoming a new front door for product discovery.

Instead of visiting multiple websites, consumers can ask questions such as:

> "What are the best laptops under $500?"

and receive a short list of recommendations directly from an AI assistant.

This creates new risks for businesses.

AI systems may:

- Exclude a business from relevant recommendations
- Provide incorrect prices
- Report outdated availability
- Misrepresent product specifications
- Provide incorrect policies or warranty information

Small businesses may have limited visibility into when these problems occur
or how frequently they occur.

ProofLayer provides businesses with a way to monitor this new AI-facing
layer of their digital presence.

---

# Core Features

## 1. AI Metric Shopper

The **AI Metric Shopper** simulates how consumers use AI assistants when
searching for products.

The system uses a predefined set of realistic shopping questions and submits
them to an AI model.

These questions can include:

### General Shopping Questions

Used to measure whether a business or product appears in relevant AI
recommendations.

Example:

> "What are some good phones under $500?"

### Product-Specific Questions

Used to evaluate whether information provided about a product is factually
accurate.

These questions can test information such as:

- Pricing
- Product specifications
- Availability
- Policies
- Warranty information

---

## 2. Visibility Monitoring

ProofLayer records whether a business or its products appear in relevant
AI-generated shopping responses.

This allows the platform to calculate metrics such as **AI Inclusion Rate**.

The goal is to help businesses understand how visible they are when
consumers use AI assistants for product discovery.

---

## 3. Accuracy Verification

ProofLayer evaluates factual claims made in AI-generated responses.

The system compares those claims against verified business or product
information provided to the platform.

For example:

### Verified Product Information

Product: Example Phone  
Storage: 128 GB  
Price: $399  
Availability: In Stock

### AI-Generated Information

> "The Example Phone includes 256 GB of storage and costs $399."

ProofLayer can identify that the storage specification conflicts with the
verified product information.

This discrepancy can then be documented for review.

---

## 4. Discrepancy Ticketing System

When ProofLayer detects a discrepancy between AI-generated information and
verified information, the platform creates a ticket.

A ticket can contain:

- The AI-generated claim
- The verified information
- The detected discrepancy
- Supporting evidence
- Severity level
- Suggested corrective action
- Review status

The ticket system gives businesses a centralized way to track inaccurate
information discovered during AI testing.

---

## 5. Human-in-the-Loop Governance

ProofLayer uses human oversight for corrective actions.

The system can automatically identify and document discrepancies, but a
human can review proposed corrections before action is taken.

Tickets can be:

- Reviewed
- Approved
- Rejected
- Tracked through resolution

This approach allows ProofLayer to automate monitoring while maintaining
human accountability over business decisions.

---

# How ProofLayer Works

```text
Predefined Shopping Questions
            |
            v
     AI Metric Shopper
            |
            v
    AI-Generated Response
            |
            v
      Claim Extraction
            |
            v
 Compare Against Verified Data
            |
            v
      Discrepancy Found?
         /        \
       No          Yes
       |            |
       v            v
 Record Result   Create Ticket
                    |
                    v
                Human Review
                 /       \
            Approve     Reject
                |
                v
          Corrective Action
                |
                v
               Retest
