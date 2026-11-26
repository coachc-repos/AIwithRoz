targetScope = 'resourceGroup'

@description('Azure region for every resource. Pick a region that offers Azure AI Foundry.')
param location string

@description('Short name prefix. Lowercase letters and numbers only. Combined with a hash of this resource group so names stay stable and are not taken from another subscription.')
@minLength(3)
@maxLength(12)
param namePrefix string

@description('Blob container for API-key settings saved in the web UI.')
param settingsContainerName string = 'app-settings'

@description('Blob container for finished videos.')
param videosContainerName string = 'finished-videos'

var suffix = take(uniqueString(resourceGroup().id), 6)
var aiName = toLower('${take(namePrefix, 10)}${suffix}ai')
var storageName = toLower('${take(namePrefix, 8)}${suffix}st')
var projectName = '${namePrefix}-project'

resource ai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    // Required for Foundry projects (accounts/projects) on an AIServices account.
    allowProjectManagement: true
    customSubDomainName: aiName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: ai
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: '${namePrefix} ScriptCraft'
    description: 'ScriptCraft hackathon Foundry project'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource settingsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: settingsContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource videosContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: videosContainerName
  properties: {
    publicAccess: 'None'
  }
}

output aiAccountName string = ai.name
output aiAccountId string = ai.id
output customSubDomain string = aiName
output aiPrincipalId string = ai.identity.principalId
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output storageAccountName string = storage.name
output storageAccountId string = storage.id
output settingsContainer string = settingsContainer.name
output videosContainer string = videosContainer.name
output locationName string = location
