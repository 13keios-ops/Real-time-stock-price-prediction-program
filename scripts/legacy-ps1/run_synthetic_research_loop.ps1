python -m app --seed-synthetic-data --symbol 005930 --minutes 90
python -m app --build-minute-bars
python -m app --build-feature-dataset
python -m app --train-baseline --horizon-min 15
