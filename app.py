from flask import Flask, render_template, request

app = Flask(__name__, template_folder='web')

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    if request.method == 'POST':
        url = request.form.get('url', '')
        result = {'url': url, 'items': []}
    return render_template('index.html', result=result)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
