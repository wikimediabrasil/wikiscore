<img src="https://img.shields.io/github/issues/WikiMovimentoBrasil/wikiscore?style=flat"/> <img src="https://img.shields.io/github/license/WikiMovimentoBrasil/wikiscore?style=flat"/> <img src="https://img.shields.io/github/languages/top/WikiMovimentoBrasil/wikiscore?style=flat"/> <img
src="https://img.shields.io/github/last-commit/WikiMovimentoBrasil/wikiscore?style=flat"/> [![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=wikimovimentobrasil_wikiscore&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=wikimovimentobrasil_wikiscore) [![Endpoint Badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fwikiscore-test.toolforge.org%2Fbadge.php)](https://translatewiki.net/wiki/Translating:WikiScore)



# WikiScore

This is an tool used to manage contests created and managed by WikiMovimento Brasil. It allows evaluators to validate editions made to articles participating in said contests, and also adds up the points earned by participants. Different contest evaluators can have their own profile, and their own separate validation history of the contributions they have checked.

The system's informations comes from local databases, which contain the data on the articles editions. These databases are fed by cron jobs, which must be set up separetely.


## Basic Django Application Setup

### Prerequisites

- Python 3.x
- Django 4.x
- pip (Python package installer)

### Installation

1. Clone the repository:

```bash
git clone https://github.com/WikiMovimentoBrasil/wikiscore.git
cd wikiscore
```

2. Create and activate a virtual environment:

```bash
python3 -m venv env
source env/bin/activate
```

3. Install the required packages:

```bash
pip install -r requirements.txt
```

4. Apply the migrations:

```bash
python manage.py migrate
```

## Creating a Superuser on Django Console

1. Run the following command to create a superuser:

```bash
python manage.py createsuperuser
```

2. Follow the prompts to enter the username, email, and password for the superuser. Make sure the username matches the username on Wikimedia, so you can log-in with OAuth.

## Setting up OAuth for Logging In

1. Register your application on the [Wikimedia OAuth](https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration) to obtain the consumer key and secret. Ensure that your request:
    - Uses OAuth version 1.0a
    - Sets "http://127.0.0.1:8000/" as the callback URL
    - Grants permission solely for user identity verification

2. Create your `.env` file and add the following settings:

```python
SOCIAL_AUTH_MEDIAWIKI_KEY = 'your_consumer_key'
SOCIAL_AUTH_MEDIAWIKI_SECRET = 'your_consumer_secret'
SECRET_KEY = 'your_Django_secret_key'
```

## Creating a Group on Admin Interface and Tying Users to Groups

1. Start the development server:

```bash
python manage.py runserver
```

2. Visit 127.0.0.1:8000 on your preferred browser and log in via OAuth using the superuser account.

3. Visit 127.0.0.1:8000/admin/ and navigate to the "Groups" section.

3. Create a new group and add yourself to the group as a "Manager".

## Setting up a Cronjob

1. Open your crontab file:

```bash
crontab -e
```

2. Add the following line to the crontab file to run the update command every 10 minutes:

```bash
*/10 * * * * /path/to/your/virtualenv/bin/python /path/to/your/project/manage.py update
```

Replace `/path/to/your/virtualenv` and `/path/to/your/project` with the appropriate paths for your environment.

## Creating Contests

For detailed instructions on creating contests, please refer to the [GitHub Wiki](https://github.com/WikiMovimentoBrasil/wikiscore/wiki) of this repository.