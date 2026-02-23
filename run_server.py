if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Force o host para 127.0.0.1 para alinhar com o ngrok
    app.run(host='127.0.0.1', port=5000)