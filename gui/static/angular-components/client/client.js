'use strict';

goog.provide('grrUi.client.module');

goog.require('grrUi.client.addClientsLabelsDialogDirective.AddClientsLabelsDialogDirective');
goog.require('grrUi.client.clientSearchBoxDirective.ClientSearchBoxDirective');
goog.require('grrUi.client.clientStatusIconsDirective.ClientStatusIconsDirective');
goog.require('grrUi.client.clientUsernamesDirective.ClientUsernamesDirective');
goog.require('grrUi.client.clientsListDirective.ClientsListDirective');
goog.require('grrUi.client.removeClientsLabelsDialogDirective.RemoveClientsLabelsDialogDirective');
goog.require('grrUi.core.module');
goog.require('grrUi.semantic.module');


/**
 * Angular module for clients-related UI.
 */
grrUi.client.module = angular.module('grrUi.client',
                                     ['ui.bootstrap',
                                      grrUi.core.module.name,
                                      grrUi.semantic.module.name]);

grrUi.client.module.directive(
    grrUi.client.addClientsLabelsDialogDirective.AddClientsLabelsDialogDirective
        .directive_name,
    grrUi.client.addClientsLabelsDialogDirective
        .AddClientsLabelsDialogDirective);
grrUi.client.module.directive(
    grrUi.client.clientsListDirective.ClientsListDirective.directive_name,
    grrUi.client.clientsListDirective.ClientsListDirective);
grrUi.client.module.directive(
    grrUi.client.clientSearchBoxDirective.ClientSearchBoxDirective
        .directive_name,
    grrUi.client.clientSearchBoxDirective.ClientSearchBoxDirective);
grrUi.client.module.directive(
    grrUi.client.clientStatusIconsDirective.ClientStatusIconsDirective
        .directive_name,
    grrUi.client.clientStatusIconsDirective.ClientStatusIconsDirective);
grrUi.client.module.directive(
    grrUi.client.clientUsernamesDirective.ClientUsernamesDirective
        .directive_name,
    grrUi.client.clientUsernamesDirective.ClientUsernamesDirective);
grrUi.client.module.directive(
    grrUi.client.removeClientsLabelsDialogDirective
        .RemoveClientsLabelsDialogDirective.directive_name,
    grrUi.client.removeClientsLabelsDialogDirective
        .RemoveClientsLabelsDialogDirective);
