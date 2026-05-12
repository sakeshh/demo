try:
    import great_expectations as gx
    print(f"GX Version: {gx.__version__}")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
