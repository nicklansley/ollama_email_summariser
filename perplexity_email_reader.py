#!/usr/bin/env python3
"""
Gmail Email Analysis Script with Perplexity API
Analyzes emails from the past 24 hours and provides categorization and summaries
"""

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from openai import OpenAI
import email
import email.message
import html2text
import imaplib
import json
import os
import re
import smtplib

load_dotenv()

class GmailAnalyzer:
    def __init__(self):
        self.gmail_account_username = os.getenv("GMAIL_USERNAME")
        self.gmail_account_password = os.getenv("GMAIL_PASSWORD")
        self.perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
        self.HOURS_TO_FETCH = 24
        self.categories = [
            'BUSINESS', 'CHARITY', 'EDUCATION', 'ENTERTAINMENT', 'ENVIRONMENT',
            'FINANCE', 'FOOD', 'GOVERNMENT', 'HEALTH', 'LGBTQ+', 'LEGAL',
            'NEWS', 'PERSONAL', 'PROMOTIONAL', 'RELIGION', 'SCIENCE',
            'SHOPPING', 'SOCIAL', 'SPORT', 'TECHNOLOGY', 'TRAVEL', 'WORK'
        ]

        # Initialize Perplexity API client
        self.perplexity_client = OpenAI(
            api_key=self.perplexity_api_key,
            base_url="https://api.perplexity.ai"
        )

    def connect_to_server(self):
        """Connect to Gmail IMAP server"""
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.gmail_account_username, self.gmail_account_password)
            print("Successfully connected to Gmail!")
            return mail
        except Exception as e:
            print(f"Error connecting to Gmail: {e}")
            return None

    def get_all_message_ids(self, mail):
        """Fetch all message IDs from the past 24 hours"""
        try:
            status, messages = mail.select("inbox")
            if status != 'OK':
                print("Error selecting inbox!")
                return []

            date_hours_ago = (datetime.now() - timedelta(hours=self.HOURS_TO_FETCH)).strftime('%d-%b-%Y')
            search_criteria = f'(SINCE {date_hours_ago})'
            status, data = mail.search(None, search_criteria)
            if status != 'OK':
                print("No messages found!")
                return []

            message_ids = data[0].split()
            print(f"Found {len(message_ids)} messages from the past {self.HOURS_TO_FETCH} hours")
            return message_ids
        except Exception as e:
            print(f'Error fetching message IDs: {e}')
            return []

    def fetch_email_by_id(self, mail, email_id):
        """Fetch a single email by its ID"""
        try:
            status, data = mail.fetch(email_id, '(RFC822)')
            if status != 'OK':
                return None
            return email.message_from_bytes(data[0][1])
        except Exception as e:
            print(f"Error fetching email {email_id}: {e}")
            return None

    def extract_text_from_html(self, html_content):
        """Extract plain text from HTML content"""
        try:
            # Use html2text for better formatting
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            return h.handle(html_content)
        except:
            # Fallback to BeautifulSoup
            try:
                soup = BeautifulSoup(html_content, 'html.parser')
                return soup.get_text()
            except:
                return html_content

    def extract_email_data(self, msg):
        """Extract relevant data from email message"""
        if not msg:
            return None

        try:
            # Get basic headers
            email_data = {
                'subject': msg.get('Subject', ''),
                'from': msg.get('From', ''),
                'to': msg.get('To', ''),
                'date': msg.get('Date', ''),
                'body': '',
                'is_from_me': False
            }

            # Check if email is from the user
            if self.gmail_account_username.lower() in email_data['from'].lower():
                email_data['is_from_me'] = True
                return email_data

            # Extract body content
            body_text = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        try:
                            body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except:
                            pass
                    elif content_type == "text/html":
                        try:
                            html_content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                            body_text += self.extract_text_from_html(html_content)
                        except:
                            pass
            else:
                try:
                    content = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                    if msg.get_content_type() == "text/html":
                        body_text = self.extract_text_from_html(content)
                    else:
                        body_text = content
                except:
                    pass

            email_data['body'] = body_text.strip()
            return email_data

        except Exception as e:
            print(f"Error extracting email data: {e}")
            return None

    def fetch_messages(self, mail, message_id_list):
        """Fetch and process multiple messages"""
        email_list = []
        print("Fetching emails: ", end="", flush=True)

        for current_email_id in message_id_list:
            msg = self.fetch_email_by_id(mail, current_email_id)
            msg_data = self.extract_email_data(msg)

            if msg_data and not msg_data['is_from_me'] and msg_data['body']:
                email_list.append(msg_data)
                print('.', end='', flush=True)

        print(f"\nProcessed {len(email_list)} relevant emails")
        return email_list

    def categorize_and_summarize_email(self, email_data):
        """Use Perplexity API to categorize and summarize an email"""
        try:
            # Prepare the prompt
            email_content = f"""
            Subject: {email_data['subject']}
            From: {email_data['from']}
            Body: {email_data['body'][:2000]}...
            """

            prompt = f"""
            Please analyze this email and:
            1. Categorize it into a maximum of 3 categories from this list: {', '.join(self.categories)}
            2. Provide a concise summary paragraph (2-3 sentences)
            3. Rate the importance on a scale of 1-10 (10 being most important)

            Email content:
            {email_content}

            Please respond in JSON format:
            {{
                "categories": ["CATEGORY1", "CATEGORY2"],
                "summary": "Brief summary of the email content and purpose",
                "importance": 8
            }}
            """

            response = self.perplexity_client.chat.completions.create(
                model="sonar-pro",
                messages=[
                    {"role": "system",
                     "content": "You are an expert email analyzer. Provide accurate categorization and summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.3
            )

            # Parse the response
            response_text = response.choices[0].message.content

            # Try to extract JSON from the response
            try:
                # Look for JSON in the response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    return result
                else:
                    # Fallback parsing
                    return {
                        "categories": ["PERSONAL"],
                        "summary": "Email content could not be properly analyzed",
                        "importance": 5
                    }
            except json.JSONDecodeError:
                return {
                    "categories": ["PERSONAL"],
                    "summary": "Email content could not be properly analyzed",
                    "importance": 5
                }

        except Exception as e:
            print(f"Error analyzing email: {e}")
            return {
                "categories": ["PERSONAL"],
                "summary": f"Error analyzing email: {str(e)[:100]}",
                "importance": 5
            }

    def process_all_emails(self, email_list):
        """Process all emails for categorization and summarization"""
        processed_emails = []
        print("\nAnalyzing emails with Perplexity API...")

        for i, email_data in enumerate(email_list):
            print(f"Processing email {i + 1}/{len(email_list)}: {email_data['subject'][:50]}...")

            analysis = self.categorize_and_summarize_email(email_data)

            processed_email = {
                **email_data,
                'categories': analysis['categories'],
                'summary': analysis['summary'],
                'importance': analysis['importance']
            }

            processed_emails.append(processed_email)

        return processed_emails

    def generate_category_summaries(self, processed_emails):
        """Generate summaries for each category"""
        category_groups = {}

        # Group emails by category
        for email in processed_emails:
            for category in email['categories']:
                if category not in category_groups:
                    category_groups[category] = []
                category_groups[category].append(email)

        # Generate summary for each category
        category_summaries = {}
        print("\nGenerating category summaries...")

        for category, emails in category_groups.items():
            if len(emails) > 0:
                print(f"Summarizing {category} category ({len(emails)} emails)...")

                # Prepare summaries for this category
                email_summaries = [email['summary'] for email in emails]
                combined_summaries = "\n".join([f"- {summary}" for summary in email_summaries])

                prompt = f"""
                Please create a cohesive paragraph summary for the {category} category based on these individual email summaries:

                {combined_summaries}

                Write an easy-to-read paragraph that captures the key themes and important information from these emails.
                """

                try:
                    response = self.perplexity_client.chat.completions.create(
                        model="sonar-pro",
                        messages=[
                            {"role": "system",
                             "content": "You are an expert at creating cohesive summaries from multiple sources."},
                            {"role": "user", "content": prompt}
                        ],
                        max_tokens=300,
                        temperature=0.3
                    )

                    category_summaries[category] = response.choices[0].message.content

                except Exception as e:
                    print(f"Error generating summary for {category}: {e}")
                    category_summaries[category] = f"Summary for {category} category with {len(emails)} emails."

        return category_summaries

    def get_top_important_emails(self, processed_emails, top_n=10):
        """Get the top N most important emails"""
        # Sort by importance score (descending)
        sorted_emails = sorted(processed_emails, key=lambda x: x['importance'], reverse=True)
        return sorted_emails[:top_n]

    def generate_report(self, processed_emails, category_summaries, top_emails):
        """Generate the final report"""
        report = f"""
# Gmail Email Analysis Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary
Analyzed {len(processed_emails)} emails from the past {self.HOURS_TO_FETCH} hours.

## Category Summaries

"""

        # Add category summaries
        for category, summary in category_summaries.items():
            report += f"### {category}\n{summary}\n\n"

        # Add top 10 important emails (brief)
        report += "## Top 10 Most Important Emails (Brief)\n\n"
        for i, email in enumerate(top_emails, 1):
            report += f"{i}. **{email['subject'][:60]}{'...' if len(email['subject']) > 60 else ''}** - {email['summary'][:80]}{'...' if len(email['summary']) > 80 else ''} (Importance: {email['importance']}/10)\n\n"

        # Add top 10 important emails (detailed)
        report += "## Top 10 Most Important Emails (Detailed Summaries)\n\n"
        for i, email in enumerate(top_emails, 1):
            report += f"### {i}. {email['subject']}\n"
            report += f"**From:** {email['from']}\n"
            report += f"**Categories:** {', '.join(email['categories'])}\n"
            report += f"**Importance:** {email['importance']}/10\n"
            report += f"**Summary:** {email['summary']}\n\n"

        return report

    def send_email_report(self, report):
        """Send the report via email"""
        try:
            print("Sending email report...")

            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.gmail_account_username
            msg['To'] = self.gmail_account_username
            msg['Subject'] = f"Gmail Analysis Report - {datetime.now().strftime('%Y-%m-%d')}"

            # Add body
            msg.attach(MIMEText(report, 'plain'))

            # Send email
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.gmail_account_username, self.gmail_account_password)
            server.send_message(msg)
            server.quit()

            print("Email report sent successfully!")

        except Exception as e:
            print(f"Error sending email: {e}")
            print("Report content:")
            print(report)

    def run(self):
        """Main execution method"""
        print("Starting Gmail Email Analysis using Perplexity AI...")

        # Connect to Gmail
        mail = self.connect_to_server()
        if not mail:
            return

        try:
            # Get message IDs
            message_ids = self.get_all_message_ids(mail)
            if not message_ids:
                print("No messages found in the specified time range.")
                return

            # Fetch emails
            email_list = self.fetch_messages(mail, message_ids)
            if not email_list:
                print("No relevant emails found.")
                return

            # Process emails with Perplexity API
            processed_emails = self.process_all_emails(email_list)

            # Generate category summaries
            category_summaries = self.generate_category_summaries(processed_emails)

            # Get top important emails
            top_emails = self.get_top_important_emails(processed_emails)

            # Generate report
            report = self.generate_report(processed_emails, category_summaries, top_emails)

            # Send email report
            self.send_email_report(report)

        finally:
            # Clean up
            mail.close()
            mail.logout()
            print("Gmail connection closed.")


if __name__ == "__main__":
    analyzer = GmailAnalyzer()
    analyzer.run()
