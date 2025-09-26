import ollama
class AI:
    def __init__(self, ollama_url, ollama_model):
        self.client = ollama.Client(host=ollama_url)
        self.model = ollama_model
        self.messages = []

    def question_persistent(self, question):
        self.messages.append({'role': 'user', 'content': question})
        response = self.client.chat(
            model=self.model,
            messages=self.messages,)['message']['content']
        self.messages.append({'role': 'assistant', 'content': response})
        return response


    def question(self, question):
        response = self.client.chat(
            model=self.model,
            messages=[*self.messages, {'role': 'user', 'content': question}]
        )['message']['content']
        self.messages.append({'role': 'assistant', 'content': response})
        return response