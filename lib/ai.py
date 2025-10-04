from openai import OpenAI
import re
import json

class AI:
    def __init__(self, logger, api_url, api_key, model):
        self.logger = logger
        self.client = OpenAI(base_url=api_url, api_key=api_key)
        self.model = model
        self.messages = [{'role': 'system', 'content':'You are a helpful assistant.'}]

    def question_persistent(self, question):
        response = self.question(question)
        self.messages.append({'role': 'user', 'content': question})
        self.messages.append({'role': 'assistant', 'content': response})
        return response


    def question(self, question):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[*self.messages, {'role': 'user', 'content': question}],
            max_tokens=4_000
        )
        return response.choices[0].message.content

    def question_json(self, question):
        for i in range(3):
            try:
                response = self.question(question)
                parsed = json.loads(self.clean_markdown_code_block(response))
                return parsed
            except json.decoder.JSONDecodeError:
                continue
        self.logger.error('Could not parse question JSON')
        return None

    def clean_markdown_code_block(self, text):
        # Remove surrounding triple backticks
        pattern = r'^```.*?\n(.*?)\n```$'
        match = re.match(pattern, text, re.DOTALL)
        if match:
            return match.group(1)
        return text
