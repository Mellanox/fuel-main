import os

import json
import mock
from mock import call
from django.test import TestCase
from django.db.models import Model
from django.conf import settings
from celery.task import task

from nailgun import tasks
from nailgun import models
from nailgun import exceptions
from nailgun import task_helpers


class TestTasks(TestCase):

    fixtures = ['default_cluster']

    def setUp(self):
        self.cluster = models.Cluster.objects.get(pk=1)
        self.nodes = models.Node.objects.all()
        self.node = self.nodes[0]
        self.components = models.Com.objects.all()
        self.component = self.components[0]
        self.roles = models.Role.objects.all()

    def tearDown(self):
        pass

    @mock.patch('nailgun.tasks.tcp_ping')
    @mock.patch('nailgun.tasks.SshConnect')
    @mock.patch('nailgun.tasks._provision_node')
    def test_bootstrap_node(self, pn_mock, ssh_mock, tp_mock):
        ssh = ssh_mock.return_value
        ssh.run.return_value = True
        pn_mock.return_value = True
        tp_mock.return_value = True

        self.assertEquals(self.node.status, "ready")
        res = tasks.bootstrap_node.delay(self.node.id, self.component.name)
        self.assertEquals(res.state, "SUCCESS")
        node = models.Node.objects.get(id=self.node.id)
        self.assertEquals(node.status, "ready")

    @mock.patch('nailgun.tasks.tcp_ping')
    @mock.patch('nailgun.tasks.SshConnect')
    def test_bootstrap_calls_provision_and_ssh(self, ssh_mock, tp_mock):
        ssh = ssh_mock.return_value
        ssh.run = mock.MagicMock(return_value=True)
        tp_mock.return_value = True
        self.node.status = "discover"
        self.node.save()

        tasks._provision_node = mock.MagicMock(return_value=None)
        tasks.bootstrap_node(self.node.id, self.component.name)
        self.assertEquals(tasks._provision_node.call_args_list,
                [call(self.node.id)])
        self.assertEquals(ssh.run.call_args_list,
                [call('/opt/nailgun/bin/deploy %s' % self.component.name)])

    @mock.patch('nailgun.tasks.tcp_ping')
    @mock.patch('nailgun.tasks.SshConnect')
    def test_bootstrap_does_not_call_provision(self, ssh_mock, tp_mock):
        ssh = ssh_mock.return_value
        ssh.run.return_value = True
        tp_mock.return_value = True
        tasks._provision_node = mock.MagicMock(return_value=None)

        tasks.bootstrap_node(self.node.id, self.component.name)
        self.assertEquals(tasks._provision_node.call_args_list, [])

    @mock.patch('nailgun.tasks.tcp_ping')
    @mock.patch('nailgun.tasks.SshConnect')
    @mock.patch('nailgun.tasks._provision_node')
    def test_bootstrap_raises_deploy_error(self, pn_mock, ssh_mock, tp_mock):
        ssh = ssh_mock.return_value
        ssh.run.return_value = False
        pn_mock.return_value = True
        tp_mock.return_value = True

        with self.assertRaises(exceptions.DeployError):
            tasks.bootstrap_node(self.node.id, self.component.name)

    @mock.patch('nailgun.tasks.tcp_ping')
    @mock.patch('nailgun.tasks.SshConnect')
    @mock.patch('nailgun.tasks._provision_node')
    def test_bootstrap_puts_error_in_task(self, pn_mock, ssh_mock, tp_mock):
        ssh = ssh_mock.return_value
        ssh.run.return_value = False
        pn_mock.return_value = True
        tp_mock.return_value = True

        self.assertEquals(self.node.status, "ready")
        res = tasks.bootstrap_node.delay(self.node.id, self.component.name)
        self.assertEquals(res.state, "FAILURE")
        self.assertIsInstance(res.result, exceptions.DeployError)
        self.assertTrue(res.ready)
        node = models.Node.objects.get(id=self.node.id)
        self.assertEquals(node.status, "error")

    @mock.patch('nailgun.tasks.TaskPool')
    def test_one_recipe_deploy_cluster(self, tp):
        tasks.deploy_cluster(self.cluster.id)
        expected = [call()]
        for node in self.cluster.nodes.all():
            for role in node.roles.all():
                for component in role.components.all():
                    expected.append(call().push_task([{
                        'args': [node.id, component.name],
                        'func': tasks.bootstrap_node,
                        'kwargs': {}
                    }]))
        expected.append(call().push_task(tasks.update_cluster_status,
                                         (self.cluster.id,)))
        expected.append(call().apply_async())
        self.assertEquals(tasks.TaskPool.mock_calls, expected)

#   FIXME(vkramskikh): recipe test, rework using components and points
#    @mock.patch('nailgun.tasks.TaskPool')
#    def test_deploy_cluster_with_recipe_deps(self, tp):
#        # 0: 1,2;  1: 2;  2: ;  3: 2
#        # Rigth order: 2,1,0,3
#        rcps = [models.Recipe() for x in range(4)]
#        for i, rec in enumerate(rcps):
#            rec.recipe = 'cookbook::recipe%s@0.1' % i
#            rec.save()
#
#        rcps[0].depends = [rcps[1], rcps[2]]
#        rcps[1].depends = [rcps[2]]
#        rcps[2].depends = []
#        rcps[3].depends = [rcps[2]]
#        map(lambda r: r.save(), rcps)
#
#        roles = [models.Role() for x in range(3)]
#        for i, role in enumerate(roles):
#            role.name = "Role%s" % i
#            role.save()
#
#        roles[0].recipes = [rcps[0], rcps[2]]
#        roles[1].recipes = [rcps[3]]
#        roles[2].recipes = [rcps[1]]
#        map(lambda r: r.save(), roles)
#
#        nodes = [models.Node() for x in range(2)]
#        for i, node in enumerate(nodes):
#            node.name = "Node-%s" % i
#            node.id = "FF000000000%s" % i
#            node.ip = "127.0.0.%s" % i
#            node.cluster_id = 1
#            node.save()
#        nodes[0].roles = [roles[0]]
#        nodes[1].roles = [roles[1], roles[2]]
#
#        tasks.deploy_cluster('1')
#        expected = [
#            # init
#            call(),
#            # first recipe, no deps, defined in setUp
#            call().push_task(tasks.create_solo, ('1', self.recipe.id)),
#            call().push_task([{'args': [self.node.id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            # Applying in order 2-> 1-> 0-> 3
#            call().push_task(tasks.create_solo, ('1', rcps[2].id)),
#            call().push_task([{'args': [nodes[0].id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            call().push_task(tasks.create_solo, ('1', rcps[1].id)),
#            call().push_task([{'args': [nodes[1].id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            call().push_task(tasks.create_solo, ('1', rcps[0].id)),
#            call().push_task([{'args': [nodes[0].id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            call().push_task(tasks.create_solo, ('1', rcps[3].id)),
#            call().push_task([{'args': [nodes[1].id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            # Last task for chord to succeed
#            call().push_task(tasks.update_cluster_status, ('1',)),
#            call().apply_async()
#        ]
#        self.assertEquals(tasks.TaskPool.mock_calls, expected)

#   FIXME(vkramskikh): recipe test, rework using components and points
#    def test_deploy_cluster_error_when_recipe_not_in_cluster(self):
#        rcps = [models.Recipe() for x in range(4)]
#        for i, rec in enumerate(rcps):
#            rec.recipe = 'cookbook::recipe%s@0.1' % i
#            rec.save()
#        rcps[0].depends = [rcps[1], rcps[2]]
#        rcps[1].depends = [rcps[2]]
#        rcps[2].depends = [rcps[3]]
#        rcps[3].depends = []
#        map(lambda r: r.save(), rcps)
#
#        roles = [models.Role() for x in range(3)]
#        for i, role in enumerate(roles):
#            role.name = "Role%s" % i
#            role.save()
#
#        roles[0].recipes = [rcps[0], rcps[3]]
#        roles[1].recipes = [rcps[2]]
#        map(lambda r: r.save(), roles)
#        self.node.roles = roles
#        self.node.save()
#
#        graph = {}
#        for recipe in models.Recipe.objects.filter(
#                    recipe__in=DeployGenerator.recipes(1)):
#            graph[recipe.recipe] = [r.recipe for r in recipe.depends.all()]
#
#        self.assertRaises(exceptions.DeployError, tasks.deploy_cluster, '1')

    @mock.patch('nailgun.tasks.TaskPool')
    def test_deploy_cluster_takes_right_cluster(self, tp):
        node = models.Node()
        node.id = "010000000007"
        node.ip = "127.0.0.1"
        # It will be node from other cluster
        node.cluster_id = 2
        node.save()
        node.roles = [self.roles[0]]
        node.save()

        tasks.deploy_cluster(self.cluster.id)
        expected = [call()]
        for node in self.cluster.nodes.all():
            for role in node.roles.all():
                for component in role.components.all():
                    expected.append(call().push_task([{
                        'args': [node.id, component.name],
                        'func': tasks.bootstrap_node,
                        'kwargs': {}
                    }]))
        expected.append(call().push_task(tasks.update_cluster_status,
                                         (self.cluster.id,)))
        expected.append(call().apply_async())
        self.assertEquals(tasks.TaskPool.mock_calls, expected)

#   FIXME(vkramskikh): recipe test, rework using components
#    def test_deploy_cluster_nodes_with_same_recipes_generates_group(self, tp):
#        # Adding second node with same recipes/roles
#        node = models.Node()
#        node.id = "FFF000000007"
#        node.ip = "127.0.0.1"
#        node.cluster_id = 1
#        node.save()
#        node.roles = [self.role]
#        node.save()
#
#        tasks.deploy_cluster('1')
#        expected = [
#            call(),
#            call().push_task(tasks.create_solo, ('1', self.recipe.id)),
#            call().push_task([{'args': [self.node.id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}},
#                              {'args': [node.id, self.component.name],
#                    'func': tasks.bootstrap_node, 'kwargs': {}}]),
#            call().push_task(tasks.update_cluster_status, ('1',)),
#            call().apply_async()
#        ]
#
