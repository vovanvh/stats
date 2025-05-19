## build and run (or rerun) dev environment

docker build -f docker/python/dev/Dockerfile -t vovanvh/voca:stats-dev .
docker-compose --project-name my-stats-dev down
docker-compose --project-name my-stats-dev up -d
docker logs -f krys-stats

## build and run (or rerun) prod environment

docker build -f docker/python/prod/Dockerfile -t vovanvh/voca:stats-prod .
docker-compose -f docker-compose.prod.yaml --project-name my-stats-prod down
docker-compose -f docker-compose.prod.yaml --project-name my-stats-prod up -d
docker logs -f krys-stats-prod

# Python

pip freeze > requirements.txt

