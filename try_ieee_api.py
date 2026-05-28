import requests
def get_ieee_data(api_key, query_string):
    base_url = "http://ieeexploreapi.ieee.org/api/v1/search/articles"
    
    params = {
        'apikey': api_key,
        'querytext': query_string,
        'format': 'json',
        'max_records': 10,
        'start_record': 1
    }
    
    response = requests.get(base_url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        articles = data['articles']
        
        for article in articles:
            title = article['title']
            authors = ', '.join([author['full_name'] for author in article['authors']['authors']])
            publication_year = article['publication_date'].split('-')[0]
            
            print(f"Title: {title}")
            print(f"Authors: {authors}")
            print(f"Publication Year: {publication_year}\n")
    else:
        print("Failed to retrieve data")
# Example usage of function with a hypothetical API key and search term.
get_ieee_data('zbwa95r35hmdy9fm45euntcu', 'artificial intelligence')