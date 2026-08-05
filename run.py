from sicof import create_app

app = create_app()

if __name__ == "__main__":
    # debug se toma de FLASK_DEBUG (.env), nunca fijo en el código.
    app.run(debug=app.config["DEBUG"])
