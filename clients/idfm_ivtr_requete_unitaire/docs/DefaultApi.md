# idfm_ivtr_requete_unitaire.DefaultApi

All URIs are relative to *https://prim.iledefrance-mobilites.fr/marketplace*

Method | HTTP request | Description
------------- | ------------- | -------------
[**get_passages**](DefaultApi.md#get_passages) | **GET** /stop-monitoring | 


# **get_passages**
> object get_passages(monitoring_ref, line_ref=line_ref)



Horaires estimés des prochains passages aux arrêts.   Actuellement, les horaires de prochains passages à un arrêt en temps réel ne sont disponibles que pour une partie du réseau d’Ile-de-France. L’ensemble des arrêts du réseau seront progressivement disponibles.  Le Jeu de données Périmètre des données temps réel disponibles expose la liste des arrêts par ligne/ transporteurs concernés par ce service.  Les requêtes et réponses sont exprimées au format SIRI Lite, vous trouverez plus d’informations sur ce format d’échange de données dans la documentation technique.  Point d'entrée pour récupérer les informations de type \"Passage\"

### Example


```python
import idfm_ivtr_requete_unitaire
from idfm_ivtr_requete_unitaire.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to https://prim.iledefrance-mobilites.fr/marketplace
# See configuration.py for a list of all supported configuration parameters.
configuration = idfm_ivtr_requete_unitaire.Configuration(
    host = "https://prim.iledefrance-mobilites.fr/marketplace"
)


# Enter a context with an instance of the API client
with idfm_ivtr_requete_unitaire.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = idfm_ivtr_requete_unitaire.DefaultApi(api_client)
    monitoring_ref = 'monitoring_ref_example' # str | Stop Point ID (exemple arrêt Châtelet les Halles : \"STIF:StopPoint:Q:473921:\")   ou Stop Area ID (exemple zone de corespondance Châtelet les Halles : \"STIF:StopArea:SP:474151:\")
    line_ref = 'line_ref_example' # str | Identifiant CodifLigne de la ligne. (Exemple RER A : \"STIF:Line::C01742:\") (optional)

    try:
        api_response = api_instance.get_passages(monitoring_ref, line_ref=line_ref)
        print("The response of DefaultApi->get_passages:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling DefaultApi->get_passages: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **monitoring_ref** | **str**| Stop Point ID (exemple arrêt Châtelet les Halles : \&quot;STIF:StopPoint:Q:473921:\&quot;)   ou Stop Area ID (exemple zone de corespondance Châtelet les Halles : \&quot;STIF:StopArea:SP:474151:\&quot;) | 
 **line_ref** | **str**| Identifiant CodifLigne de la ligne. (Exemple RER A : \&quot;STIF:Line::C01742:\&quot;) | [optional] 

### Return type

**object**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | OK |  -  |
**400** | BAD Request : La requête contient des identifiants qui sont inconnus |  -  |
**500** | Internal Server Error |  -  |
**503** | Service Unavailable |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

