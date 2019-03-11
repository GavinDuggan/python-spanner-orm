# python3
# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os
import unittest
from unittest import mock

from spanner_orm import error
from spanner_orm.admin import migration_executor
from spanner_orm.admin import migration_manager
from spanner_orm.admin import update


class TestMigration(object):

  def __init__(self,
               migration_id,
               prev_migration_id,
               upgrade_update=None,
               downgrade_update=None):
    self._id = migration_id
    self._prev = prev_migration_id
    self._upgrade_update = upgrade_update or update.NoUpdate()
    self._downgrade_update = downgrade_update or update.NoUpdate()

  @property
  def migration_id(self):
    return self._id

  @property
  def prev_migration_id(self):
    return self._prev

  def upgrade(self):
    return self._upgrade_update

  def downgrade(self):
    return self._downgrade_update


class MigrationsTest(unittest.TestCase):
  TEST_DIR = os.path.dirname(__file__)
  TEST_MIGRATIONS_DIR = os.path.join(TEST_DIR, 'migrations')

  def test_retrieve(self):
    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    migrations = manager.migrations
    self.assertEqual(len(migrations), 3)
    self.assertEqual(migrations[2].prev_migration_id,
                     migrations[1].migration_id)
    self.assertEqual(migrations[1].prev_migration_id,
                     migrations[0].migration_id)

  def test_generate(self):
    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    path = manager.generate('test migration')
    try:
      migration = manager._migration_from_file(path)
      self.assertIsNotNone(migration.migration_id)
      self.assertIsNotNone(migration.prev_migration_id)
      self.assertIsNotNone(migration.upgrade)
      self.assertIsNotNone(migration.downgrade)
    finally:
      os.remove(path)

  def test_order_migrations(self):
    first = TestMigration('1', None)
    second = TestMigration('2', '1')
    third = TestMigration('3', '2')
    migrations = [third, first, second]
    expected_order = [first, second, third]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    self.assertEqual(manager._order_migrations(migrations), expected_order)

  def test_order_migrations_with_no_none(self):
    first = TestMigration('2', '1')
    second = TestMigration('3', '2')
    third = TestMigration('4', '3')
    migrations = [third, first, second]
    expected_order = [first, second, third]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    self.assertEqual(manager._order_migrations(migrations), expected_order)

  def test_order_migrations_error_on_unclear_successor(self):
    first = TestMigration('1', None)
    second = TestMigration('2', '1')
    third = TestMigration('3', '1')
    migrations = [third, first, second]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    with self.assertRaisesRegex(error.SpannerError, 'unclear successor'):
      manager._order_migrations(migrations)

  def test_order_migrations_error_on_unclear_start_migration(self):
    first = TestMigration('1', None)
    second = TestMigration('3', '2')
    migrations = [first, second]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    with self.assertRaisesRegex(error.SpannerError, 'no valid previous'):
      manager._order_migrations(migrations)

  def test_order_migrations_error_on_circular_dependency(self):
    first = TestMigration('1', '3')
    second = TestMigration('2', '1')
    third = TestMigration('3', '2')
    migrations = [third, first, second]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    with self.assertRaisesRegex(error.SpannerError, 'No valid migration'):
      manager._order_migrations(migrations)

  def test_order_migrations_error_on_no_successor(self):
    first = TestMigration('1', None)
    second = TestMigration('2', '3')
    third = TestMigration('3', '2')
    migrations = [third, first, second]

    manager = migration_manager.MigrationManager(self.TEST_MIGRATIONS_DIR)
    with self.assertRaisesRegex(error.SpannerError, 'no successor'):
      manager._order_migrations(migrations)

  def test_filter_migrations(self):
    executor = migration_executor.MigrationExecutor('', '')
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    migrations = [first, second, third]

    migrated = {'1': True, '2': False, '3': False}
    with mock.patch.object(executor, '_migration_status_map', migrated):
      filtered = executor._filter_migrations(migrations, False, None)
      self.assertEqual(filtered, [second, third])

      filtered = executor._filter_migrations(migrations, False, '2')
      self.assertEqual(filtered, [second])

      filtered = executor._filter_migrations(reversed(migrations), True, '1')
      self.assertEqual(filtered, [first])

  def test_filter_migrations_error_on_bad_last_migration(self):
    executor = migration_executor.MigrationExecutor('', '')
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    migrations = [first, second, third]

    migrated = {'1': True, '2': False, '3': False}
    with mock.patch.object(executor, '_migration_status_map', migrated):
      with self.assertRaises(error.SpannerError):
        executor._filter_migrations(migrations, False, '1')

      with self.assertRaises(error.SpannerError):
        executor._filter_migrations(migrations, False, '4')

  def test_validate_migrations(self):
    executor = migration_executor.MigrationExecutor('', '')
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    with mock.patch.object(executor, 'migrations') as migrations:
      migrations.return_value = [first, second, third]

      migrated = {'1': True, '2': False, '3': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        executor._validate_migrations()

      migrated = {'1': False, '2': False, '3': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        executor._validate_migrations()

  def test_validate_migrations_error_on_unmigrated_after_migrated(self):
    executor = migration_executor.MigrationExecutor('', '')
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    with mock.patch.object(executor, 'migrations') as migrations:
      migrations.return_value = [first, second, third]

      migrated = {'1': False, '2': True, '3': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        with self.assertRaises(error.SpannerError):
          executor._validate_migrations()

      migrated = {'1': False, '2': False, '3': True}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        with self.assertRaises(error.SpannerError):
          executor._validate_migrations()

  def test_validate_migrations_error_on_unmigrated_first(self):
    executor = migration_executor.MigrationExecutor('', '')
    first = TestMigration('2', 1)
    with mock.patch.object(executor, 'migrations') as migrations:
      migrations.return_value = [first]

      migrated = {'1': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        with self.assertRaises(error.SpannerError):
          executor._validate_migrations()

      migrated = {}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        with self.assertRaises(error.SpannerError):
          executor._validate_migrations()

  @mock.patch('spanner_orm.admin.api.SpannerAdminApi')
  @mock.patch('spanner_orm.api.SpannerApi')
  def test_migrate(self, api, admin_api):
    api.connect = mock.Mock()
    admin_api.connect = mock.Mock()

    executor = migration_executor.MigrationExecutor(
        1, 2, credentials=3, project=4)
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    with mock.patch.object(executor, 'migrations') as migrations:
      migrations.return_value = [first, second, third]
      migrated = {'1': True, '2': False, '3': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        executor.migrate()
        self.assertEqual(migrated, {'1': True, '2': True, '3': True})
    api.connect.assert_called_once_with(1, 2, credentials=3, project=4)
    admin_api.connect.assert_called_once_with(1, 2, credentials=3, project=4)

  @mock.patch('spanner_orm.admin.api.SpannerAdminApi')
  @mock.patch('spanner_orm.api.SpannerApi')
  def test_rollback(self, api, admin_api):
    api.connect = mock.Mock()
    admin_api.connect = mock.Mock()

    executor = migration_executor.MigrationExecutor(
        1, 2, credentials=3, project=4)
    first = TestMigration('1', None)
    second = TestMigration('2', 1)
    third = TestMigration('3', 2)
    with mock.patch.object(executor, 'migrations') as migrations:
      migrations.return_value = [first, second, third]
      migrated = {'1': True, '2': False, '3': False}
      with mock.patch.object(executor, '_migration_status_map', migrated):
        executor.rollback('1')
        self.assertEqual(migrated, {'1': False, '2': False, '3': False})
    api.connect.assert_called_once_with(1, 2, credentials=3, project=4)
    admin_api.connect.assert_called_once_with(1, 2, credentials=3, project=4)


if __name__ == '__main__':
  logging.basicConfig()
  unittest.main()
