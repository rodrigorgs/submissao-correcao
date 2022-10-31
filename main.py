from email.policy import default
import json
import sys
import requests
import re
import os
import subprocess
from collections import defaultdict
from bs4 import BeautifulSoup

API_BASE_PATH = os.getenv('SUBMISSAO_API_BASE_PATH')
USERNAME = os.getenv('SUBMISSAO_USERNAME')
PASSWORD = os.getenv('SUBMISSAO_PASSWORD')

class SubmissaoService:
    def __init__(self, api_base_path):
        self.api_base_path = api_base_path
        self.token = None

    def login(self, username, password):
        resp = requests.post(f'{self.api_base_path}/login.php', \
            json = {
                'username': username,
                'password': password
            })

        if (resp.status_code == 200):
            self.token = resp.text
        else:
            raise Exception("Erro ao fazer login")

    def get_assignments(self, pattern='%'):
        r = requests.get(f'{self.api_base_path}/get-assignments.php', \
            params={'assignment_url': pattern})
        if (r.status_code == 200):
            return r.text.strip().split('\n')
        else:
            raise Exception("Erro ao obter assignments")

    def evaluate_all(self, update=False, overwrite=False):
        ret = {}
        for assignment in self.get_assignments():
            ass = AssignmentService(assignment, self.api_base_path, self.token)
            ret.update(ass.evaluate_all(update, overwrite))
        return ret

class AssignmentService:
    def __init__(self, assignment_url, api_base_path, token):
        self.assignment_url = assignment_url
        self.api_base_path = api_base_path
        self.token = token
        self.codes = None
        self.answers = None

    def get_code_in_textareas(self):
        if self.codes is None:
            r = requests.get(self.assignment_url)
            soup = BeautifulSoup(r.content, 'html5lib')
            ret = []
            for textarea in soup.find_all('textarea', 'code'):
                ret.append(textarea.contents[0])
            self.codes = ret
        return self.codes
    
    def _get_tests_string_index(self, code):
        '''Returns index where tests start in a string (code)'''
        regex = re.compile('^### Test', re.MULTILINE)
        m = regex.search(code)
        if m:
            return m.start()
        else:
            return None

    def get_tests(self, question_index):
        code = self.get_code_in_textareas()[question_index]
        idx = self._get_tests_string_index(code)
        if idx:
            return code[idx:]
        else:
            return ''

    def _get_stats(self):
        if '0.0.0.0' in self.assignment_url:
            return ''
        print('get_stats ', self.assignment_url)
        resp = requests.get(f'{self.api_base_path}/assignment-stats.php', \
            params = {
                'url': self.assignment_url,
                'submission_type': 'batch'
            })

        if (resp.status_code == 200):
            return resp.text
        else:
            raise Exception("Erro ao consultar estatísticas")

    def get_submitters(self):
        csv = self._get_stats()
        rows = [line.split('\t') for line in csv.strip().split("\n")]
        return [row[0] for row in rows[1:]]

    def get_number_of_questions(self):
        csv = self._get_stats()
        return len(csv.split('\n')[0].split('\t')) - 2

    def get_answers(self, username):
        if self.answers is None:
            r = requests.post(f'{self.api_base_path}/get-answers.php', \
                headers = {
                    'Authorization': 'Bearer ' + self.token
                },
                json = {
                    'assignment_url': self.assignment_url,
                    'username': username,
                    'submission_type': 'batch'
                })
            if r.status_code != 200:
                raise Exception("Erro ao obter resposta:", username)
            self.answers = r.json()
        return self.answers

    def get_all_answers(self):
        if 'ex-python-estatico' in self.assignment_url:
            return []
        if self.answers is None:
            payload = {
                    'assignment_url': self.assignment_url,
                    'username': '%',
                    'submission_type': 'batch'
                }
            r = requests.post(f'{self.api_base_path}/get-answers2.php', \
                headers = {
                    'Authorization': 'Bearer ' + self.token
                },
                json = payload)
            if r.status_code != 200:
                raise Exception("Erro ao obter respostas")
            print('json ', payload)
            # print('content ', r.content.decode("utf-8") )
            if len(r.content) < 5:
                return []
            else:
                try:
                    self.answers = r.json()
                except json.decoder.JSONDecodeError as e:
                    print(r.text)
                    raise e

        return self.answers

    def answer_with_tests(self, answer, question_index):
        idx_test_in_answer = self._get_tests_string_index(answer)
        if idx_test_in_answer is not None:
            answer = answer[0:idx_test_in_answer]
        
        tests = self.get_tests(question_index)
        return answer + tests

    def evaluate(self, answer, question_index):
        '''
        Return True if the answer passes the tests, false otherwise
        '''
        # answer = self.get_answers(username)[question_index]
        # answer += '\n' + self.get_tests(question_index)
        answer = self.answer_with_tests(answer, question_index)
        cmd = ['docker', 'run', '-i', '--rm', 'python:3.10-alpine', '/bin/sh', '-c', 'python', '-']
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, errors = proc.communicate(input=answer)
        proc.wait()
        return proc.returncode == 0

    def update_score(self, id, score):
        r = requests.post(f'{self.api_base_path}/update-score.php', \
            headers = {
                'Authorization': 'Bearer ' + self.token
            },
            json = {
                'id': id,
                'score': score
            })
        if r.status_code != 200:
            raise Exception("Erro ao atualizar score")

    def evaluate_all(self, update=False, overwrite=False):
        n = self.get_number_of_questions()
        results = defaultdict(lambda: [0] * n)
        answers = self.get_all_answers()
        for answer in answers:
            score = answer['score']
            if score is None or overwrite:
                success = self.evaluate(answer['answer'], answer['question_index'])
                score = 1.0 if success else 0.0
                if update:
                    self.update_score(answer['id'], score)
            else:
                score = float(score)
            username = answer['username']
            question_index = answer['question_index']
            results[username][question_index] = score
            print(username, question_index, score)
        return {self.assignment_url: dict(results)}

def main():
    sub = SubmissaoService(API_BASE_PATH)
    sub.login(USERNAME, PASSWORD)
    print(sub.evaluate_all(update=True, overwrite=False))

if __name__ == '__main__':
    main()
