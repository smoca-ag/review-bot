from openai import OpenAI
class AI:
    def __init__(self, api_url, api_key, model):
        self.client = OpenAI(base_url=api_url, api_key=api_key)
        self.model = model
        self.messages = [{'role': 'system', 'content':'You are a meticulous AI code reviewer.'}]

    def question_persistent(self, question):
        response = self.question(question)
        self.messages.append({'role': 'user', 'content': question})
        self.messages.append({'role': 'assistant', 'content': response})
        return response


    def question(self, question):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[*self.messages, {'role': 'user', 'content': question}],
        )

        return response.choices[0].message.content
