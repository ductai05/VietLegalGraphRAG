import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="VietLegalGraphRAG Entrypoint")
    parser.add_argument('--task', type=str, required=True, help="Task to run (e.g. data_prep, train, infer)")
    args = parser.parse_args()

    if args.task == 'data_prep':
        print("Running data preparation...")
        # Import and run data pipeline from src/
    elif args.task == 'train':
        print("Running training pipeline...")
        # Import and run training pipeline from src/
    elif args.task == 'infer':
        print("Running inference...")
        # Import and run services from src/
    else:
        print(f"Unknown task: {args.task}")
        sys.exit(1)

if __name__ == "__main__":
    main()

