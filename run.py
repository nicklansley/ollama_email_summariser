from datetime import datetime, timedelta, timezone
from email.header import decode_header
import email
import email.message
import imaplib
import os
import re
import smtplib

from dotenv import load_dotenv
import ollama

load_dotenv()

allowed_categories_list = [
    'BUSINESS', 'CHARITY', 'EDUCATION', 'ENTERTAINMENT', 'ENVIRONMENT', 'FINANCE', 'FOOD', 'GOVERNMENT', 'HEALTH',
    'LGBTQ+', 'LEGAL', 'NEWS', 'PERSONAL', 'PROMOTIONAL', 'RELIGION', 'SCIENCE', 'SHOPPING', 'SOCIAL', 'SPORT',
    'TECHNOLOGY', 'TRAVEL', 'WORK'
]


def fetch_email_by_id(mail, email_id):
    status, msg_data = mail.fetch(email_id, "(RFC822)")
    raw_email = msg_data[0][1]
    return email.message_from_bytes(raw_email)


def format_concluding_paragraph(paragraph: str) -> str:
    # Regular expression to find numeric bullet points
    regex = r"(\d+\.\s)"
    # Substitute the matches with <br> following the pattern
    formatted_paragraph = re.sub(regex, r"<br><br>\1", paragraph)

    # Look for phrase 'Top 10 messages to read first:' and replace with '<br><br>Top 10 messages to read first:<br><br>'
    formatted_paragraph = formatted_paragraph.replace('Top 10 messages to read first:',
                                                      '<br><br>Top 10 messages to read first:<br><br>')
    return formatted_paragraph


class EmailSummariser:
    def __init__(self):
        self.ai_model_concluding_summary_prompt = ""
        self.ai_model_category_headlines_prompt = ""
        self.ai_model_top_headlines_prompt = ""
        self.ai_model_combined_prompt = ""
        self.ai_model_convert_html_to_plain_text_prompt = ""
        self.gmail_account_username = os.getenv("GMAIL_USERNAME")
        self.gmail_account_password = os.getenv("GMAIL_PASSWORD")
        self.INDIVIDUAL_EMAIL_SUMMARIES = os.getenv("INDIVIDUAL_EMAIL_SUMMARIES", "NO") == "YES"
        self.NEWSREADER_SCRIPT = os.getenv("NEWSREADER_SCRIPT", "NO") == "YES"
        self.NUM_CTX = int(os.getenv("NUM_CTX", "8000"))

        self.HOURS_TO_FETCH = os.getenv("HOURS_TO_FETCH", "24")
        self.HOURS_TO_FETCH = int(self.HOURS_TO_FETCH) if self.HOURS_TO_FETCH.isdigit() else 24

        self.ignore_sender_list = os.getenv("IGNORE_SENDERS", "").split(',')

        self.messages_data = {
            'messages_list': [],
            'category_summary_dict': {}
        }

        self.categorising_ai_model = os.getenv("CATEGORISING_AI_MODEL", 'llama3.1:latest')
        self.summarising_ai_model = os.getenv("SUMMARISING_AI_MODEL", 'llama3.1:latest')

        self.init_ai_prompts()

    def init_ai_prompts(self):
        self.ai_model_combined_prompt = """
        You are tasked with both categorising and summarising email messages. 
        
        First, categorize the email using a single word. 
        Choose from this list of categories. Do not use any other categories:
        {allowed_categories_list}. To help you, if you see a word in the email that matches a category, 
        prioritise that word over others. If not, use your judgement as to which category best describes the content.
        
        Next, summarise the message. 
        You are an expert at summarising email messages and prefer to use clauses instead of complete sentences in 
        order to make your summary concise and to the point. 
        Be brief and to the point in a single paragraph. Don't use bullet points, lists, or other structured formats. 
        Do not answer any questions you may find in the messages. Use British English spelling.
        
        Respond with the category word as the very first word, followed by a colon, then the summary of the message.
        
        The user will provide you with a message to categorize and summarise. This message will have been received 
        within the previous <HOURS_TO_FETCH> hours.
        """.replace('<HOURS_TO_FETCH>', str(self.HOURS_TO_FETCH))

        self.ai_model_top_headlines_prompt = """
        You are an expert scriptwriter for a news radio station. 
        Create engaging and informative news headlines from the emails received in the past <HOURS_TO_FETCH> hours. 
        Your summary should be a paragraph suitable for a news bulletin opening. Be fluid and expressive, and don't include 
        any bullet points or lists. Make it easy for the newsreader to present the information.
        Highlight any significant news. Your script will be read out at <TIME_STRING> so phrase 'morning', 'afternoon' and other time-based words accordingly as needed.  
        Conclude with your own observations on the messages, starting with "In my opinion..."."
        """.replace('<HOURS_TO_FETCH>', str(self.HOURS_TO_FETCH)).replace('<TIME_STRING>', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


        self.ai_model_category_headlines_prompt = """
        You are an expert scriptwriter for a news radio station. 
        Condense the emails received in the past <HOURS_TO_FETCH> hours into an engaging and informative 
        single-paragraph news bulletin summary about a particular news category, highlighting noteworthy points even if the emails seem mundane. 
        Be concise, use British English spelling. Make it easy for the newsreader to present the information.
        and conclude with your personal observations starting with "In my opinion...".
        Author the script as if it were being added into the middle of a existing larger script which the newsreader is 
        currently reading. Don't add any script tags such as [NEWSREADER NAME] or [Pause] or [Intro music fades out] as these are already elsewhere.
        """.replace('<HOURS_TO_FETCH>', str(self.HOURS_TO_FETCH)).replace('<TIME_STRING>', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        self.ai_model_concluding_summary_prompt = """
        You are an expert scriptwriter for a news radio station. 
        Write a concluding paragraph for a news bulletin, expressing your own opinion and observations on 
        the messages received in the past <HOURS_TO_FETCH> hours. 
        Begin your output with "In conclusion, ".
        After writing this paragraph, list the top 10 messages you think are the most important, explaining 
        'why it matters' in each case.
        Start this list with "Top 10 messages to read first:"
        """.replace('<HOURS_TO_FETCH>', str(self.HOURS_TO_FETCH))

        self.ai_model_convert_html_to_plain_text_prompt = """
        You are an expert at converting HTML content to plain text. There is no need to retain any formatting or links,
        just return the plain text content. The user will provide you with an HTML message to convert.
        """

    def add_categories_to_prompt(self):
        self.ai_model_combined_prompt = self.ai_model_combined_prompt.replace(
            '{allowed_categories_list}', ', '.join(allowed_categories_list))

    @staticmethod
    def format_body(body_text: str) -> str:
        # replace all '\uXXXX' characters with a space
        processed_text = body_text.encode('ascii', 'ignore').decode('ascii')

        # Remove any web addresses by searching for 'https', 'http' and 'www', then removing the text up to the next space
        processed_text = ' '.join([word for word in processed_text.split() if
                                   'https' not in word and 'http' not in word and 'www' not in word])

        # remove any extra spaces
        while '  ' in processed_text:
            processed_text = processed_text.replace('  ', ' ')

        return processed_text

    def get_gmail_messages(self):
        if not self.gmail_account_username or not self.gmail_account_password:
            print(
                "Email gmail_account_username or gmail_account_password not set in environment variables or .env file")
            exit(1)

        mail = self.connect_to_server()
        message_id_list = self.get_all_message_ids(mail)
        print('Total emails found in Inbox:', len(message_id_list))
        messages_list = self.fetch_and_filter_messages(mail, message_id_list)
        print(len(messages_list), f'messages from the past {self.HOURS_TO_FETCH} hours to process')
        mail.logout()
        return messages_list

    def connect_to_server(self):
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(self.gmail_account_username, self.gmail_account_password)
        return mail

    def get_all_message_ids(self, mail):
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
            return message_ids
        except Exception as e:
            print(f'Error fetching message IDs: {e}')
            return []

    def fetch_messages(self, mail, message_id_list):
        email_list = []
        for current_email_id in message_id_list:
            msg = fetch_email_by_id(mail, current_email_id)
            msg_data = self.extract_email_data(msg)
            print('.', end='', flush=True)
            email_list.append(msg_data)
        return email_list

    def filter_recent_emails(self, email_list):
        date_hours_ago = datetime.now(timezone.utc) - timedelta(hours=self.HOURS_TO_FETCH)
        recent_emails = []

        for msg_data in email_list:
            if not msg_data['date_sent']:
                continue

            try:
                email_date = datetime.strptime(msg_data['date_sent'], '%a, %d %b %Y %H:%M:%S %z')
                if email_date < date_hours_ago:
                    continue
            except:
                continue

            recent_emails.append(msg_data)
        return recent_emails

    def filter_ignored_senders(self, email_list):
        filtered_emails = [msg for msg in email_list if msg['sender'] not in self.ignore_sender_list]
        return filtered_emails

    def deduplicate_emails(self, email_list):
        deduped_email_list = []
        sorted_email_list = sorted(
            email_list,
            key=lambda x: datetime.strptime(x['date_sent'], '%a, %d %b %Y %H:%M:%S %z'),
            reverse=True
        )

        before_deduped_count = len(sorted_email_list)

        for message in sorted_email_list:

            if not any(
                    message['sender'] == deduped_email['sender'] and message['subject'] == deduped_email['subject']
                    for deduped_email in deduped_email_list
            ):
                deduped_email_list.append(message)

        after_deduped_count = len(deduped_email_list)

        if after_deduped_count < before_deduped_count:
            print('\n', before_deduped_count - after_deduped_count, 'emails were duplicates and have been removed')

        return deduped_email_list

    def fetch_and_filter_messages(self, mail, message_id_list):
        try:
            email_list = self.fetch_messages(mail, message_id_list)
            email_list = self.filter_recent_emails(email_list)
            email_list = self.filter_ignored_senders(email_list)
            email_list = self.deduplicate_emails(email_list)

            print(f'{len(email_list)} messages found with readable text in the body of the message')
            return email_list

        except Exception as e:
            print('Error fetching and filtering messages:', e)
            print('Traceback:', e.__traceback__.tb_lineno)
            return []

    def extract_email_data(self, msg) -> dict:
        try:
            subject = self.decode_mime_header(msg["Subject"]).replace('\n', '')
        except:
            subject = '(no subject)'

        try:
            sender = msg.get("From")
        except:
            sender = '(unknown sender)'

        try:
            message_id = msg.get('Message-ID')
        except:
            message_id = '(unknown message id)'

        try:
            date_sent = msg.get("Date")
        except:
            date_sent = '(unknown date)'

        try:
            plain_text, html = self.extract_body(msg)
        except:
            plain_text = ''
            html = ''

        return {
            'message_id': message_id,
            'date_sent': date_sent,
            'sender': sender,
            'subject': subject,
            'plain_text': self.format_body(plain_text),
            'html': html,
            'summary': '',
            'category': 'UNPROCESSED'
        }

    @staticmethod
    def decode_mime_header(header_value: str) -> str:
        decoded_header, encoding = decode_header(header_value)[0]
        if isinstance(decoded_header, bytes):
            return decoded_header.decode(encoding or 'utf-8')
        return decoded_header

    @staticmethod
    def extract_body(msg):
        plain_text = ''
        html = ''

        def decode_payload(encoded_payload):
            if encoded_payload:
                decoded_payload = encoded_payload.decode(errors='ignore')
                if '<html' not in decoded_payload:
                    return decoded_payload + "\n"
            return ''

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if "text/plain" in content_type:
                    payload = part.get_payload(decode=True)
                    plain_text += decode_payload(payload)
                elif "text/html" in content_type:
                    payload = part.get_payload(decode=True)
                    html += decode_payload(payload)
        else:
            payload = msg.get_payload(decode=True)
            plain_text += decode_payload(payload)

        return plain_text, html

    def ai_summarise_email(self, email_content: str) -> str:
        response = ollama.chat(
            model=self.summarising_ai_model,
            options={"num_ctx": self.NUM_CTX},
            messages=[
                {'role': 'system', 'content': self.ai_model_combined_prompt},
                {'role': 'user', 'content': email_content},
            ])
        return response['message']['content'].strip().replace('\n', '.')

    def call_ai_model(self, model, prompt, user_content):
        response = ollama.chat(
            model=model, options={"num_ctx": self.NUM_CTX},
            messages=[
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': user_content},
            ])

        return response['message']['content'].strip()

    def ai_convert_html_to_plain_text(self, email_content: str) -> str:
        try:
            plain_text = self.call_ai_model(self.summarising_ai_model, self.ai_model_convert_html_to_plain_text_prompt,
                                            email_content)
            return plain_text.replace('\n', '. ').replace('..', '.').strip()
        except Exception as e:
            print('Error converting HTML to plain text: ', e)
            return ''

    def ai_author_category_headlines(self, email_message_list: list) -> str:
        content = ''.join(
            f"From: {message_data['sender']}\nSubject: {message_data['subject']}\nMessage: {message_data['summary']}\n\n"
            for message_data in email_message_list)

        try:
            ai_response = self.call_ai_model(
                self.summarising_ai_model, self.ai_model_category_headlines_prompt, content
            ).replace('\n', '. ')

            ai_response_sentences = [sentence for sentence in ai_response.split('. ') if
                                     'summary' not in sentence and 'paragraph' not in sentence and sentence]
            ai_response = '. '.join(ai_response_sentences)

            if 'In my opinion' in ai_response:
                ai_response = '<p>' + ai_response.replace('In my opinion', '<br><br><i>In my opinion') + '</i></p>'
            else:
                ai_response = '<p>' + ai_response + '</p>'

            if ai_response.startswith('"') and ai_response.endswith('"'):
                ai_response = ai_response[1:-1]

            return ai_response + '. '
        except Exception as e:
            print('Error authoring category headlines:', e)
            return ''

    def ai_author_concluding_paragraph(self, email_body_text: str) -> str:
        print('Authoring concluding paragraph...')
        try:
            paragraph = self.call_ai_model(
                self.summarising_ai_model, self.ai_model_concluding_summary_prompt, email_body_text
            )
            return format_concluding_paragraph(paragraph)

        except Exception as e:
            print('Error authoring concluding paragraph:', e)
            return ''

    def ai_author_overall_headlines(self, summarised_group_content: str) -> str:
        print('Authoring top headlines summary...')
        try:
            headlines = self.call_ai_model(
                self.summarising_ai_model, self.ai_model_top_headlines_prompt, summarised_group_content
            )
            # Put in two line breaks every fourth sentence to make the text more readable
            headlines = '.<br><br>'.join([sentence for i, sentence in enumerate(headlines.split('. ')) if i % 4 != 0])
            return headlines
        except Exception as e:
            print('Error authoring overall headlines:', e)
            return ''

    def update_message_list(self, message_id: str, summary: str):
        for message in self.messages_data['messages_list']:
            if message['message_id'] == message_id:
                message['summary'] = summary
                break

    def author_summary_email(self, email_list: list) -> tuple:
        try:
            earliest_message = email_list[0]["date_sent"]
            latest_message = email_list[-1]["date_sent"]

            email_body = f"<p>Here are the AI-powered summaries of the emails from {earliest_message} to {latest_message}:<br><br></p>"
            revised_categories_list = []

            for message in email_list:
                if message['category'] != 'UNPROCESSED' and message['category'] not in revised_categories_list:
                    revised_categories_list.append(message['category'])

            if 'PERSONAL' in revised_categories_list:
                revised_categories_list.remove('PERSONAL')
                revised_categories_list.insert(0, 'PERSONAL')

            if 'NEWS' in revised_categories_list:
                revised_categories_list.remove('NEWS')
                revised_categories_list.insert(1, 'NEWS')

            category_counter = 0

            if 'category_summary_dict' not in self.messages_data or not self.messages_data.get('category_summary_dict'):
                self.messages_data['category_summary_dict'] = {}

            for category in revised_categories_list:
                filtered_messages_list = [message for message in email_list if message["category"] == category]
                if category not in self.messages_data.get('category_summary_dict', {}) or self.messages_data['category_summary_dict'][category] == '':
                    category_counter += 1
                    print(f'Processing category: {category} ({category_counter} of {len(revised_categories_list)}) - {len(filtered_messages_list)} messages...')
                    if len(filtered_messages_list) <= 10:
                        self.messages_data['category_summary_dict'][category] = self.ai_author_category_headlines(filtered_messages_list)
                        email_body += f'<hr>Category: {category} (from {len(filtered_messages_list)} messages)<br>'
                        email_body += self.messages_data['category_summary_dict'][category]
                    else:
                        # process messages in batches of 10
                        group_counter = 1
                        for i in range(0, len(filtered_messages_list), 10):
                            batch_messages = filtered_messages_list[i:i + 10]
                            category_group_name = f'{category}-{group_counter}'
                            if f'{category}-{group_counter}' in self.messages_data['category_summary_dict']:
                                self.messages_data['category_summary_dict'][category_group_name] += self.ai_author_category_headlines(batch_messages)
                            else:
                                self.messages_data['category_summary_dict'][category_group_name] = self.ai_author_category_headlines(batch_messages)

                            email_body += f'<hr>Category: {category_group_name} (from {len(filtered_messages_list)} messages)<br>'
                            email_body += self.messages_data['category_summary_dict'][category_group_name]
                            group_counter += 1

                email_body += '\n\n'

            if self.NEWSREADER_SCRIPT and (
                    'headlines_summary' not in self.messages_data.get('headlines_summary', {}) or self.messages_data[
                'headlines_summary'] == ''):
                self.messages_data['headlines_summary'] = self.ai_author_overall_headlines(email_body)

            email_body = '<p>Overall Headline Summary:<br>' + self.messages_data[
                'headlines_summary'] + '<br><br>' + email_body + '</p>'

            if 'concluding_paragraph' not in self.messages_data.get('concluding_paragraph', {}) or self.messages_data[
                'concluding_paragraph'] == '':
                self.messages_data['concluding_paragraph'] = self.ai_author_concluding_paragraph(email_body)

            email_body += '<hr>Concluding Paragraph:<br>' + self.messages_data['concluding_paragraph']

            if self.INDIVIDUAL_EMAIL_SUMMARIES:
                email_body += '<hr>Individual Email Summaries:<br>'
                for category in revised_categories_list:
                    filtered_messages_list = [message for message in email_list if message["category"] == category]
                    email_body += f'----------------------------------------<br>{category}<br>'
                    for message in filtered_messages_list:
                        email_body += '----------------------------------------<br><br>'
                        email_body += f"From: {message['sender']} on {message['date_sent']} with subject '{message['subject']}':<br>"
                        email_body += f"Category: {message['category']}<br>"
                        email_body += f"Summary: {message['summary']}<br><br>"

            return email_body, earliest_message, latest_message

        except Exception as e:
            print('Error authoring summary email:', e)
            print('stacktrace:', e.__traceback__.tb_lineno)
            return '', '', ''

    def send_summary_email(self, email_body: str, earliest_datetime: str, latest_datetime: str):
        if not self.gmail_account_username or not self.gmail_account_password:
            print(
                "Email gmail_account_username or gmail_account_password not set in environment variables or .env file")
            exit(1)

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.gmail_account_username, self.gmail_account_password)
                msg = email.message.EmailMessage()
                msg['Subject'] = f'Summary of messages from {earliest_datetime} to {latest_datetime}'
                msg['From'] = self.gmail_account_username
                msg['To'] = self.gmail_account_username
                msg.add_alternative(email_body, subtype='html')
                server.send_message(msg)
                print('Summary email sent successfully')
        except Exception as e:
            print('Error sending summary email:', e)


    def wake_up_ai(self):
        print('Waking up AI models...')
        try:
            response = ollama.chat(
                model=self.summarising_ai_model,
                messages=[
                    {'role': 'system',
                     'content': 'The user will send you a "wake up" message. Just respond with a pleasantry!'},
                    {'role': 'user', 'content': 'Hello AI, this is a test message to wake you up! I hope you are well!'}
                ])

            print(f'AI model "{self.summarising_ai_model}" is awake and says: {response["message"]["content"]}')

            response = ollama.chat(
                model=self.categorising_ai_model,
                messages=[
                    {'role': 'system',
                     'content': 'The user will send you a "wake up" message. Just respond with a pleasantry!'},
                    {'role': 'user', 'content': 'Hello AI, this is a test message to wake you up! I hope you are well!'}
                ])

            print(f'AI model "{self.categorising_ai_model}" is awake and says: {response["message"]["content"]}')
        except Exception as e:
            print(f'Error waking up AI models: {e}')

    def run(self):
        try:
            start_time = datetime.now(timezone.utc)
            print(f'Starting email summarisation process at {start_time}')

            # Wake up the AI models (this causes them to be loaded into memory of they are not already loaded)
            self.wake_up_ai()

            # Add the allowed categories to the summarising prompt
            self.add_categories_to_prompt()

            # Display the ignored senders list
            print('Ignored senders list:', self.ignore_sender_list)

            # Get the messages from the Gmail account
            self.messages_data['messages_list'] = self.get_gmail_messages()

            process_counter = 1
            for message in self.messages_data['messages_list']:
                try:
                    # 'UNPROCESSED' is the initial category for all messages
                    if message['category'] == 'UNPROCESSED':
                        if len(message['plain_text']) > 0:
                            email_text = message['plain_text']
                        elif len(message['html']) > 0:
                            print('Converting HTML to plain text using AI')
                            email_text = self.ai_convert_html_to_plain_text(message['html'])
                        else:
                            email_text = ''

                        if len(email_text) < 100:
                            print('Email content too short to summarise')
                        else:
                            print('Processing message:', process_counter, 'of',
                                  len(self.messages_data['messages_list']),
                                  ' - ', round(len(email_text) / 1000, 1), 'Kb from', message['sender'],
                                  '\n\t\t\twith subject:', message['subject'])

                            # If the category is empty, 'UNOPROCESSED' or contains a space, get the AI to summarise the email
                            # and if necessary, re-summarise it!
                            while message['category'] not in allowed_categories_list:
                                response = self.ai_summarise_email(email_text)

                                # The frst word of the response is the category
                                message['category'] = response.split(':')[0].strip().upper()

                                # If the category is not in the allowed list, the AI has not understood the
                                # email (or the content fell foul of the model's moral filters, so delete the summary.
                                if message['category'] not in allowed_categories_list:
                                    message['category'] = 'UNPROCESSED'
                                    message['summary'] = '(AI did not understand the email content)'
                                    break

                                # The rest of the response is the summary
                                message['summary'] = response.split(':')[1].strip()

                            print('\t\t\tCategory:', message['category'])

                            self.update_message_list(message['message_id'], message['summary'])

                except Exception as e:
                    print('Error processing message:', e)

                process_counter += 1

            print('All emails summarised successfully - now authoring summary email')
            email_message, earliest_message_datetime, latest_message_datetime = self.author_summary_email(
                self.messages_data['messages_list'])

            if len(email_message) == 0:
                print('No emails to summarise')
                return

            print('Now sending summary email to', self.gmail_account_username)
            self.send_summary_email(email_message, earliest_message_datetime, latest_message_datetime)

            end_time = datetime.now(timezone.utc)
            print("Email AI Summarisation Ended at:", end_time)
            print('Duration:', end_time - start_time)

        except Exception as e:
            print(f"An error occurred during the summarisation process: {e}")


if __name__ == "__main__":
    try:
        summarizer = EmailSummariser()
        summarizer.run()
    except KeyboardInterrupt:
        print("Email summarisation process interrupted by user")
